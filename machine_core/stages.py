"""Rotary stages (REVISION_PLAN.md P2.7, B06, C8) – Qt-free successor of RotMotor_Cotroller.

Own hardware (C8): Feetech SC / STS servos in wheel mode on their own serial bus, closed loop on the PC (PID at 50 Hz),
stage angle = motor angle / gear ratio (3:1). The PID is taken over unchanged from v1.0.

Safety (B06): in wheel mode a servo keeps its last speed until it is told otherwise, so the PC must stop it whenever
control ends:
- disconnect / interpreter exit (atexit): speed 0 to every motor before the port closes;
- a failed read or write: speed 0 for that motor in this cycle; `max_failures` in a row or any exception in the
  loop -> fault: speed 0 to every motor, the loop ends, every wait raises `StageError` until reconnect;
- `move_to_angle(wait_for_position=True)` gives up after `timeout` (StageTimeout) and stops the motor; `cancel()`
  (e.g. the machine stop) stops the motor and returns False;
- `stop_motor` sends speed 0 and suspends the control until the next target (v1.0 only wrote speed 0, which the
  loop overrode 20 ms later).
A crash that kills the process without atexit (power loss of the PC, kill) still leaves the last speed active – the
servos have no watchdog in wheel mode (VERIFY in the STS3215 manual).

Position mode (C16, `control_mode="position"`, opt-in until the hardware test tools/st3215_position_test.py has
passed): the servo's own position loop in multi-turn absolute mode (mode 0, both angle limits 0, full-angle
feedback). The PC only writes the goal (±32767 ticks ≈ ±8 motor turns) and watches the position; there is no PC
PID, so no stick-slip hunting, and a dead PC leaves the servo standing at its last goal. Stop = goal := present
position. (Step mode 3 is not used: its present position is the distance to the target, not a position.)
"""
import atexit
import threading
import time
from pathlib import Path

TICKS_PER_REV = 4096
GOAL_LIMIT = 30000          # position mode: goal register ±32767 (bit 15 = sign), kept clear of the end
MODE_POSITION, MODE_WHEEL = 0, 1
REG_MIN_ANGLE, REG_MAX_ANGLE, REG_PHASE, REG_MODE = 9, 11, 18, 33
PHASE_FULL_ANGLE = 0x10     # phase bit 4: feedback the full (multi-turn) angle instead of 0..4095


class StageError(Exception):
    pass


class StageTimeout(StageError):
    pass


class StageFrameError(StageError):
    """Position mode: the PC's position and the servo's goal frame do not match – torque off, not a goal."""


# --------------------------------------------------------------------------- buses

class ScservoBus:
    """The real servo board (libraries.scservo_sdk). read_pos / write_speed return None / False on a comm error."""

    def __init__(self, port, series="STS"):
        from libraries.scservo_sdk import COMM_SUCCESS, PortHandler, scscl, sms_sts
        self._ok = COMM_SUCCESS
        self.port = PortHandler(port)
        if not self.port.openPort():
            raise StageError(f"cannot open {port}")  # PortHandler default baud rate, as in v1.0
        self.driver = scscl(self.port) if series == "SC" else sms_sts(self.port)

    def ping(self, sid):
        return self.driver.ping(sid)[1] == self._ok

    def setup_wheel_mode(self, sid):
        self.driver.unLockEprom(sid)
        self.driver.WheelMode(sid)
        self.driver.LockEprom(sid)
        self.driver.EnableTorque(sid, 1)

    def setup_position_mode(self, sid):
        """C16: multi-turn absolute position mode (VERIFY on the ST3215: tools/st3215_position_test.py)."""
        if not hasattr(self.driver, "WritePosEx"):
            raise StageError("position mode needs STS servos")
        d = self.driver
        phase, result, _ = d.read1ByteTxRx(sid, REG_PHASE)
        if result != self._ok:
            raise StageError(f"motor {sid}: cannot read the phase register")
        d.EnableTorque(sid, 0)           # no jump to a goal left in the register while switching
        d.unLockEprom(sid)
        d.write1ByteTxRx(sid, REG_MODE, MODE_POSITION)
        d.write2ByteTxRx(sid, REG_MIN_ANGLE, 0)
        d.write2ByteTxRx(sid, REG_MAX_ANGLE, 0)
        d.write1ByteTxRx(sid, REG_PHASE, phase | PHASE_FULL_ANGLE)
        d.LockEprom(sid)
        pos = self.read_pos(sid)
        if pos is None or not self.write_goal(sid, pos, 0, 0):
            raise StageError(f"motor {sid}: cannot set the goal to the present position")
        d.EnableTorque(sid, 1)

    def write_goal(self, sid, goal, speed, acc):
        result, _ = self.driver.WritePosEx(sid, self.driver.scs_toscs(int(goal), 15), int(speed), int(acc))
        return result == self._ok

    def release(self, sid):
        """Torque off (the stage turns freely) – only when the PC no longer knows where the servo is."""
        self.driver.EnableTorque(sid, 0)

    def keepalive(self):
        self.driver.ReadPos(0)  # dummy read as in v1.0 ("prevents timeouts" of the board)

    def read_pos(self, sid):
        pos, result, _ = self.driver.ReadPos(sid)
        return pos if result == self._ok else None

    def write_speed(self, sid, speed, acc):
        result, _ = self.driver.WriteSpec(sid, speed, acc)
        return result == self._ok

    def close(self):
        self.port.closePort()


class SimStageBus:
    """Simulated servo board: speed in ticks/s, acceleration `acc` × 100 ticks/s² (STS units), raw position wraps.

    Faults for tests: `jammed` (ids that do not turn), `fail_reads` (ids whose reads fail), `raise_on_read`.
    `cycle_dt`: if set, the motors advance by this fixed time once per control cycle (keepalive) instead of by the
    wall clock – tests then do not depend on how busy the PC is (see C16 for what load does on the real PC).
    """

    def __init__(self, ids=(1,), positions=None, cycle_dt=None):
        self.motors = {sid: {"pos": float((positions or {}).get(sid, 0)), "speed": 0.0, "cmd": 0.0, "acc": 50,
                             "goal": None, "limit": 0.0} for sid in ids}
        self.wheel_mode = set()
        self.position_mode = set()
        self.single_turn_feedback = False   # fault for tests: position mode without full-angle feedback
        self.servo_deadband = 0             # position mode: stops this many ticks short, no move for a closer goal
        self.released = set()
        self.writes = []                 # (time, id, speed)
        self.closed = False
        self.jammed = set()
        self.fail_reads = set()
        self.raise_on_read = False
        self.cycle_dt = cycle_dt
        self.virtual_time = 0.0
        self._t = time.monotonic()
        self._lock = threading.Lock()

    def _advance(self, dt=None):
        if dt is None:
            if self.cycle_dt is not None:
                return
            now = time.monotonic()
            dt, self._t = now - self._t, now
        for sid, mo in self.motors.items():
            step = mo["acc"] * 100 * dt
            if sid in self.position_mode:
                if mo["goal"] is None or sid in self.released:
                    mo["speed"] = 0.0
                    continue
                # the servo's own loop: trapezoid to the goal, stops on the tick
                dist = mo["goal"] - mo["pos"]
                if abs(dist) <= self.servo_deadband:     # measured ST3215: stops 2-4 ticks short (C16)
                    mo["speed"] = 0.0
                    mo["pos"] = float(round(mo["pos"]))
                    continue
                brake = (2 * max(step / dt, 1e-9) * abs(dist)) ** 0.5
                want = max(-mo["limit"], min(mo["limit"], (1 if dist > 0 else -1) * min(brake, abs(dist) / dt)))
                mo["speed"] += max(-step, min(step, want - mo["speed"]))
                if sid not in self.jammed:
                    move = mo["speed"] * dt
                    if abs(dist - move) <= self.servo_deadband or abs(move) >= abs(dist):
                        # arrives: on the goal, or (dead band) that many ticks short of it
                        mo["pos"] = mo["goal"] - (1 if dist > 0 else -1) * self.servo_deadband
                        mo["speed"] = 0.0
                    else:
                        mo["pos"] += move
                continue
            mo["speed"] += max(-step, min(step, mo["cmd"] - mo["speed"]))
            if sid not in self.jammed:
                mo["pos"] += mo["speed"] * dt

    def ping(self, sid):
        return sid in self.motors

    def setup_wheel_mode(self, sid):
        self.wheel_mode.add(sid)
        self.position_mode.discard(sid)

    def setup_position_mode(self, sid):
        self.position_mode.add(sid)
        self.wheel_mode.discard(sid)

    def write_goal(self, sid, goal, speed, acc):
        with self._lock:
            if self.closed:
                raise StageError("port closed")
            self._advance()
            mo = self.motors[sid]
            mo["goal"], mo["limit"], mo["acc"] = float(goal), float(speed), acc
            self.writes.append((time.monotonic(), sid, ("goal", int(goal))))
            return True

    def release(self, sid):
        with self._lock:
            self.released.add(sid)

    def last_goal(self, sid):
        return next((w[1] for _, i, w in reversed(self.writes) if i == sid and isinstance(w, tuple)), None)

    def keepalive(self):
        if self.cycle_dt is not None:
            with self._lock:
                self.virtual_time += self.cycle_dt
                self._advance(self.cycle_dt)

    @property
    def clock(self):
        """The PID's time source: virtual with `cycle_dt`, so controller and motors share one time base."""
        return (lambda: self.virtual_time) if self.cycle_dt is not None else time.time

    def read_pos(self, sid):
        with self._lock:
            if self.closed:
                raise StageError("port closed")
            if self.raise_on_read:
                raise OSError("simulated bus error")
            self._advance()
            if sid in self.fail_reads:
                return None
            pos = self.motors[sid]["pos"]
            if sid in self.position_mode:
                pos = int(round(pos))
                return pos % TICKS_PER_REV if self.single_turn_feedback else pos  # full-angle feedback, signed
            return int(pos) % TICKS_PER_REV

    def write_speed(self, sid, speed, acc):
        with self._lock:
            if self.closed:
                raise StageError("port closed")
            self._advance()
            self.motors[sid]["cmd"], self.motors[sid]["acc"] = float(speed), acc
            self.writes.append((time.monotonic(), sid, speed))
            return True

    def last_speed(self, sid):
        return next((s for _, i, s in reversed(self.writes) if i == sid and not isinstance(s, tuple)), None)

    def close(self):
        with self._lock:
            self.closed = True


# --------------------------------------------------------------------------- one motor (PID unchanged from v1.0)

class StageMotor:
    clock = staticmethod(time.time)        # PID time source; the simulator may give a virtual one

    def __init__(self, ID, raw_position=0, speed=1000, acc=50, gear_ratio=3):
        self.ID = ID
        self.last_raw_pos = raw_position
        self.turn_count = 0
        self.total_ticks = raw_position
        self.target_ticks = raw_position
        self.speed_limit = speed
        self.acc = acc
        self.gear_ratio = gear_ratio       # C8: 3:1
        self.Kp, self.Ki, self.Kd = 1.5, 0.5, 1
        self.integral_error = 0.0
        self.last_error = 0.0
        self.last_update_time = self.clock()
        self.position_reached = True
        self.position_stable_counter = 0
        self.position_stable_threshold = 5
        self.failures = 0
        self.stopped = False             # after stop: speed 0, no control until the next target
        self.position_changed_callback = []

    def ticks(self, angle):
        return int((angle / 360.0) * TICKS_PER_REV * self.gear_ratio)

    def angle(self, ticks):
        return round((ticks / TICKS_PER_REV) * 360.0 / self.gear_ratio, 2)

    def update_from_raw(self, new_raw_pos):
        diff = new_raw_pos - self.last_raw_pos
        if diff < -2048:
            self.turn_count += 1
        elif diff > 2048:
            self.turn_count -= 1
        self.last_raw_pos = new_raw_pos
        self.total_ticks = self.turn_count * TICKS_PER_REV + new_raw_pos
        for callback in self.position_changed_callback:
            try:
                callback(self.angle(self.total_ticks))
            except Exception:
                pass  # a broken display (e.g. a closed widget) must not stop the control loop

    def set_target_angle(self, angle):
        new_target = self.ticks(angle)
        self.stopped = False
        if new_target != self.target_ticks:
            self.target_ticks = new_target
            self.integral_error = 0.0
            self.last_error = new_target - self.total_ticks
            self.last_update_time = self.clock()
        if abs(self.target_ticks - self.total_ticks) >= 3:
            # v1.0 left this to the next loop cycle (and slept 0.1 s); a wait right after must not see the old True
            self.position_reached = False
            self.position_stable_counter = 0

    def hold(self):
        """Stop: speed 0 and no control until the next target (v1.0's loop drove on to the old target)."""
        self.stopped = True
        self.target_ticks = self.total_ticks
        self.integral_error = 0.0
        self.last_error = 0.0
        self.position_reached = True

    def set_position_changed_callback(self, callback):
        """Called with the stage angle (deg) from the control thread – receivers must be thread-safe (v1.0 API)."""
        self.position_changed_callback.append(callback)

    def get_target_angle(self):
        return self.angle(self.target_ticks)

    def get_current_angle(self):
        return self.angle(self.total_ticks)

    def calculate_control_speed(self):
        """Full PID controller (v1.0). Returns speed -1000..1000."""
        now = self.clock()
        dt = now - self.last_update_time
        if dt <= 0.0001:
            dt = 0.001
        if dt > 0.5:
            dt = 0.1
        self.last_update_time = now
        if self.stopped:
            self.target_ticks = self.total_ticks
            return 0
        error = self.target_ticks - self.total_ticks
        if abs(error) < 3:
            self.integral_error = 0
            self.last_error = 0
            self.position_stable_counter += 1
            if self.position_stable_counter >= self.position_stable_threshold and not self.position_reached:
                self.position_reached = True
            return 0
        self.position_stable_counter = 0
        self.position_reached = False
        p_term = self.Kp * error
        self.integral_error += error * dt
        max_i = 400
        i_contrib = self.Ki * self.integral_error
        if i_contrib > max_i:
            self.integral_error = max_i / self.Ki
            i_contrib = max_i
        elif i_contrib < -max_i:
            self.integral_error = -max_i / self.Ki
            i_contrib = -max_i
        d_term = self.Kd * ((error - self.last_error) / dt)
        self.last_error = error
        limit = min(self.speed_limit, 1000)
        output_speed = int(max(-limit, min(limit, p_term + i_contrib + d_term)))
        min_pwr = 30
        if 0 < output_speed < min_pwr:
            output_speed = min_pwr
        if -min_pwr < output_speed < 0:
            output_speed = -min_pwr
        return output_speed


class ServoPositionMotor(StageMotor):
    """C16: the servo positions itself (multi-turn absolute mode); the PC writes the goal and corrects the rest.

    Measured on the ST3215 (2026-11-24, tests/hardware/c16): the servo stops 2-4 ticks short of its goal and does not
    move at all for a goal 1-3 ticks away (its own loop has the same break-away limit as the wheel mode). So the PC
    aims past the target by the remaining error once the servo stands still (`max_corrections` times, at most
    `max_aim` ticks past), like a nudge, without any PID on the PC.
    Reached = within `tolerance` and still for `position_stable_threshold` cycles; after the corrections within
    `accept` ticks also counts (logged), anything further away never counts (the wait times out)."""

    tolerance = 1
    accept = 4                         # ticks, measured accuracy without correction
    settle_cycles = 10                 # 0.2 s still = the servo has stopped
    max_corrections = 3
    max_aim = 12                       # ticks the goal may lie past the target

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.goal_ticks = self.total_ticks
        self.sent_goal = None          # None: (re)send the goal in the next cycle
        self.corrections = 0
        self.still_cycles = 0
        self._prev_ticks = self.total_ticks
        self.accuracy_note = None

    def update_from_raw(self, new_raw_pos):
        if abs(new_raw_pos - self.last_raw_pos) > TICKS_PER_REV // 2:
            # full-angle feedback never jumps by half a turn in one cycle: the servo reports single-turn positions,
            # so the PC's ticks and the servo's goal frame differ by whole turns
            raise StageFrameError(f"motor {self.ID}: position jumped {self.last_raw_pos} -> {new_raw_pos} "
                                  f"(no full-angle feedback?)")
        self.last_raw_pos = new_raw_pos
        self.total_ticks = new_raw_pos
        for callback in self.position_changed_callback:
            try:
                callback(self.angle(self.total_ticks))
            except Exception:
                pass

    def set_target_angle(self, angle):
        new_target = self.ticks(angle)
        if abs(new_target) > GOAL_LIMIT:
            raise StageError(f"motor {self.ID}: {angle}° is outside the servo range "
                             f"(±{self.angle(GOAL_LIMIT)}° at {self.gear_ratio:g}:1)")
        self.stopped = False
        if new_target != self.target_ticks:
            self.target_ticks = self.goal_ticks = new_target
            self.corrections = 0
            self.still_cycles = 0
        if abs(self.target_ticks - self.total_ticks) > self.tolerance or self.sent_goal != self.goal_ticks:
            self.position_reached = False
            self.position_stable_counter = 0

    def hold(self):
        """Stop where the stage is now: goal := present position (sent in the next cycle or by the caller)."""
        self.stopped = True
        self.target_ticks = self.goal_ticks = self.total_ticks
        self.sent_goal = None
        self.corrections = 0
        self.position_reached = True

    def goal_command(self):
        """One control cycle: the goal to write, or None. Updates `position_reached`."""
        self.still_cycles = self.still_cycles + 1 if self.total_ticks == self._prev_ticks else 0
        self._prev_ticks = self.total_ticks
        if self.sent_goal != self.goal_ticks:
            return self.goal_ticks
        error = self.target_ticks - self.total_ticks
        self.position_stable_counter = self.position_stable_counter + 1 if abs(error) <= self.tolerance else 0
        if self.position_reached or self.stopped:
            return None
        if self.position_stable_counter >= self.position_stable_threshold:
            self.position_reached = True
        elif self.still_cycles >= self.settle_cycles:
            if self.corrections < self.max_corrections:
                aim = max(-self.max_aim, min(self.max_aim, self.goal_ticks + error - self.target_ticks))
                self.corrections += 1
                self.still_cycles = 0
                if self.target_ticks + aim != self.goal_ticks:
                    self.goal_ticks = self.target_ticks + aim
                    return self.goal_ticks
            elif abs(error) <= self.accept:
                self.accuracy_note = f"motor {self.ID}: stands {abs(error)} ticks from the target"
                self.position_reached = True
        return None

    def goal_sent(self):
        self.sent_goal = self.goal_ticks


class LoopRecorder:
    """C16: CSV of every control cycle (time, motor, target / actual ticks, command) – does not change the control."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "w", encoding="utf-8", newline="")
        self._file.write("time,motor,target_ticks,actual_ticks,command\n")

    def __call__(self, t, sid, target, actual, command):
        if not self._file.closed:
            self._file.write(f"{t:.4f},{sid},{target},{actual},{'' if command is None else command}\n")

    def close(self):
        self._file.close()


# --------------------------------------------------------------------------- the stages

class RotaryStages:
    def __init__(self, bus_factory, gear_ratio=3, loop_interval=0.02, max_failures=5, move_timeout=100.0,
                 on_log=None, gear_ratios=None, control_mode="wheel", recorder=None):
        self.bus_factory = bus_factory     # () -> bus
        self.gear_ratio = gear_ratio       # C8: 3:1 (GT2 20:60); 5:1 upgrade planned -> per motor in gear_ratios
        self.gear_ratios = dict(gear_ratios or {})  # {motor id: ratio}, overrides gear_ratio
        self.loop_interval = loop_interval
        self.max_failures = max_failures
        self.move_timeout = move_timeout   # s, default for waits (v1.0 had 100 s, unused)
        self.on_log = on_log or (lambda text, level="info": None)
        if control_mode not in ("wheel", "position"):
            raise ValueError(f"unknown rotary control mode {control_mode!r}")
        self.control_mode = control_mode   # C16: "wheel" = v1.0 PID on the PC, "position" = the servo's own loop
        self.recorder = recorder           # (time, id, target ticks, actual ticks, command) per cycle, or None
        self.bus = None
        self.motors = []
        self.fault = None
        self.lock = threading.RLock()
        self._halt = threading.Event()
        self._thread = None
        self._atexit = False

    @property
    def connected(self):
        return self.bus is not None

    # ------------------------------------------------------------------ connection
    def connect(self):
        if self.bus is not None:
            return
        bus = self.bus_factory()
        position = self.control_mode == "position"
        motors = []
        for sid in range(1, 10):
            if bus.ping(sid):
                if position:
                    bus.setup_position_mode(sid)   # before the read: the feedback changes to the full angle
                pos = bus.read_pos(sid)
                if pos is None:
                    continue
                if not position:
                    bus.setup_wheel_mode(sid)
                kind = ServoPositionMotor if position else StageMotor
                motor = kind(sid, raw_position=pos, gear_ratio=self.gear_ratios.get(sid, self.gear_ratio))
                if hasattr(bus, "clock"):
                    motor.clock = bus.clock
                    motor.last_update_time = motor.clock()
                motors.append(motor)
        with self.lock:
            self.bus, self.motors, self.fault = bus, motors, None
        self._halt.clear()
        self._thread = threading.Thread(target=self._loop, name="rotary-control", daemon=True)
        self._thread.start()
        if not self._atexit:
            atexit.register(self._stop_at_exit)
            self._atexit = True
        self.on_log(f"rotary stages ({self.control_mode} mode): motors {[mo.ID for mo in motors]}")

    def _stop_at_exit(self):
        """Interpreter exit: speed 0 and close; the UI that would show a log line may already be gone."""
        if self.bus is None:
            return
        try:
            RotaryStages.disconnect(self)
        except Exception:
            pass

    def disconnect(self):
        if self.bus is None:
            return
        self._halt.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(1.0)
        with self.lock:
            self._all_speed_zero()
            try:
                self.bus.close()
            except Exception:
                pass
            self.bus, self.motors = None, []
        self.on_log("rotary stages disconnected")

    # ------------------------------------------------------------------ control loop
    def _loop(self):
        try:
            while not self._halt.is_set():
                with self.lock:
                    self.bus.keepalive()
                    for motor in self.motors:
                        raw = self.bus.read_pos(motor.ID)
                        if raw is None:
                            self._failure(motor, "read failed")
                            continue
                        motor.update_from_raw(raw)
                        if isinstance(motor, ServoPositionMotor):
                            command = motor.goal_command()
                            if command is not None:
                                if self.bus.write_goal(motor.ID, command, motor.speed_limit, motor.acc) is False:
                                    self._failure(motor, "write failed")
                                    continue
                                motor.goal_sent()
                            if motor.accuracy_note:
                                self.on_log(motor.accuracy_note, "warning")
                                motor.accuracy_note = None
                        else:
                            command = motor.calculate_control_speed()
                            if self.bus.write_speed(motor.ID, command, motor.acc) is False:
                                self._failure(motor, "write failed")
                                continue
                        motor.failures = 0
                        if self.recorder:
                            self.recorder(time.time(), motor.ID, motor.target_ticks, motor.total_ticks, command)
                self._halt.wait(self.loop_interval)
        except StageFrameError as e:
            self._set_fault(str(e), release=True)
        except Exception as e:
            self._set_fault(f"control loop: {e!r}")

    def _halt_motor(self, motor, release=False):
        """Stop one motor at once: wheel mode speed 0; position mode goal := present position (or torque off)."""
        motor.hold()
        try:
            if isinstance(motor, ServoPositionMotor):
                if release:
                    self.bus.release(motor.ID)
                elif self.bus.write_goal(motor.ID, motor.total_ticks, motor.speed_limit, motor.acc):
                    motor.goal_sent()
            else:
                self.bus.write_speed(motor.ID, 0, motor.acc)
        except Exception:
            pass

    def _failure(self, motor, what):
        motor.failures += 1
        if isinstance(motor, ServoPositionMotor):
            # a read failed: the servo keeps its own goal; only a write failure leaves it unknown
            if what != "read failed":
                self._halt_motor(motor)
        else:
            self._halt_motor(motor)
        if motor.failures >= self.max_failures:
            raise StageError(f"motor {motor.ID}: {what} {motor.failures}× in a row")

    def _set_fault(self, reason, release=False):
        with self.lock:
            self.fault = reason
            self._halt.set()
            self._all_speed_zero(release)
        self.on_log(f"rotary stages stopped: {reason}", "error")

    def _all_speed_zero(self, release=False):
        for motor in self.motors:
            self._halt_motor(motor, release)

    # ------------------------------------------------------------------ commands
    def _motors(self, sid):
        return list(self.motors) if sid == -1 else [mo for mo in self.motors if mo.ID == sid]

    def move_to_angle(self, sid, angle, wait_for_position=False, timeout=None, cancel=None):
        """Set the stage angle (deg, also > 360). With wait: True when reached, False if `cancel()` became true
        (the motor is stopped), StageTimeout / StageError otherwise."""
        self._check()
        with self.lock:
            motors = self._motors(sid)
            if not motors:
                raise StageError(f"no rotary motor {sid}")
            for motor in motors:
                motor.set_target_angle(angle)
        if not wait_for_position:
            return True
        deadline = time.monotonic() + (self.move_timeout if timeout is None else timeout)
        while not all(mo.position_reached for mo in motors):
            self._check()
            if cancel and cancel():
                self.stop_motor(sid)
                return False
            if time.monotonic() > deadline:
                self.stop_motor(sid)
                raise StageTimeout(f"motor {sid} did not reach {angle}° in time")
            time.sleep(0.02)
        return True

    def stop_motor(self, sid):
        with self.lock:
            for motor in self._motors(sid):
                if self.bus is not None:
                    self._halt_motor(motor)
                else:
                    motor.hold()

    def stop_all(self):
        self.stop_motor(-1)

    def get_current_angle(self, sid):
        return [mo.get_current_angle() for mo in self._motors(sid)] or None

    def _check(self):
        if self.fault:
            raise StageError(f"rotary stages in fault ({self.fault}) – reconnect")
        if self.bus is None:
            raise StageError("rotary stages not connected")
