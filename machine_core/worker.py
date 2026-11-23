"""Machine worker (REVISION_PLAN.md P2.3): the only thread that talks to the machine.

The UI (and later the job runner) only calls `submit(command)` with a dataclass from machine_core.messages and gets
events back through `on_event(event)` – called from the worker thread, the UI bridge marshals them (rule 2/3).

- Coordinates are absolute machine coordinates (C5): no G92 is ever sent; the work position is app-side only.
- Absolute moves need homing after connect; relative jogs work before.
- Multi-line sequences (G91 … G90) run in one piece on this thread (B11); no serial I/O in the UI (B12).
- `Stop` / `EmergencyStop` are written immediately from the caller's thread (`write_now`), not queued (B04).
  The UI asks for confirmation before submitting them (C2).
- Laser off (`config.laser_off`) on stop, error, ack timeout, exception in this thread, disconnect and shutdown (B01).
- After an error the state is `error` until `AcknowledgeError`; nothing resumes on its own.
No Qt.
"""
import queue
import threading
import time
from dataclasses import dataclass, field

import protocol_log
from machine_core import messages as m
from machine_core.job import JobCancelled, JobRunner, JobStep
from machine_core.marlin import ConnectionLost, MarlinConnection, MarlinError, SendsBlocked
from machine_core.state import MachineState as S, StateMachine
from machine_core.transport import SerialTransport, SimTransport, TransportClosed

SIMULATOR_PORT = "simulator"


@dataclass
class ArtisanConfig:
    """Machine settings the worker needs; filled from the settings today, from the machine profile later (P3.3)."""
    baudrate: int = 115200
    default_speed: float = 30.0          # mm/s
    max_z_speed: float = 30.0            # mm/s; also limits combined moves, as in v1.0
    laser_offsets: dict = field(default_factory=lambda: {"laser1064": (21.3, -11.3, 0.0), "laser455": (-21.0, 0.0, 0.0)})
    toolhead_line_count: dict = field(default_factory=lambda: {39: "laser1064", 34: "laser455"})  # M1006 answer incl. ok (C7)
    laser_off: tuple = ("M5", "M9")
    outputs: dict = field(default_factory=lambda: {
        "crosshair": ("M2000 L13 P1", "M2000 L13 P0"),
        "light": ("M2000 W1 P100", "M2000 W1 P0"),
        "fan": ("M2000 W2 P100", "M2000 W2 P0"),
        "air_assist": ("M8", "M9"),
    })
    # preflight limits (P2.5); machine coordinates after homing. Datasheet values, VERIFY on the machine.
    work_area: tuple = ((0.0, 400.0), (0.0, 400.0), (0.0, 400.0))  # (min, max) per X, Y, Z in mm
    max_power_s: float = 255.0           # S word
    max_power_p: float = 100.0           # P word, percent
    max_feed: float = None               # mm/min; None = not checked (Artisan limit unknown)
    home_timeout: float = 120.0
    ack_timeout: float = 10.0
    poll_interval: float = 0.1           # M114 while idle
    jog_interval: float = 0.1            # continuous jog increment


def _fmt(value: float) -> str:
    """Coordinates as sent: 4 decimals, no float noise (B25)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


class MachineWorker:
    def __init__(self, on_event=None, config: ArtisanConfig = None, transport_factory=None, rotary=None):
        self.rotary = rotary               # RotMotorCotroller-like: move_to_angle(sid, angle, wait_for_position)
        self.config = config or ArtisanConfig()
        self.on_event = on_event or (lambda event: None)
        self._transport_factory = transport_factory or self._default_transport
        self.state = StateMachine(lambda state, reason: self._emit(m.StateChanged(state.value, reason)))
        self.con = None
        self.toolhead = None
        self.laser_offset = None
        self.homed = set()                 # axes homed since connect
        self.position = None               # last known machine position (x, y, z)
        self.work_position = (0.0, 0.0, 0.0)
        self._queue = queue.Queue()
        self._jog = None                   # (axis, direction, speed) while a continuous jog runs
        self._stop_requested = threading.Event()
        self._alive = True
        self._thread = threading.Thread(target=self._run, name="machine-worker", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ public API (any thread)
    def submit(self, command):
        """Never blocks. Stop / EmergencyStop act at once; everything else runs on the worker thread in order."""
        if isinstance(command, m.EmergencyStop):
            self._emergency_stop()
        elif isinstance(command, m.Stop):
            self._stop()
        else:
            self._queue.put(command)

    def shutdown(self, timeout=3.0):
        """App exit: laser off, close the port, end the thread."""
        self._queue.put(_Shutdown())
        self._thread.join(timeout)

    @property
    def homed_all(self):
        return self.homed >= {"X", "Y", "Z"}

    # ------------------------------------------------------------------ stop paths (caller's thread)
    def _emergency_stop(self):
        con = self.con
        if con is None or con.lost:
            return
        try:
            con.stop(("M112",))  # also blocks every further send: a running job ends at once
        except ConnectionLost:
            pass
        self._stop_requested.set()
        self._jog = None
        if self.state.can(S.ESTOP):
            self.state.to(S.ESTOP, "emergency stop – restart the machine, then reconnect")

    def _stop(self):
        con = self.con
        if con is None or con.lost:
            return
        self._stop_requested.set()
        self._jog = None
        try:
            con.stop(("M410",) + tuple(self.config.laser_off))  # quick stop (discard the planner), laser off
        except ConnectionLost:
            pass
        self._queue.put(_AfterStop())

    # ------------------------------------------------------------------ worker thread
    def _run(self):
        while self._alive:
            try:
                command = self._queue.get(timeout=self._idle_wait())
            except queue.Empty:
                command = None
            try:
                if command is None:
                    self._idle_tick()
                else:
                    self._handle(command)
            except (SendsBlocked, JobCancelled):
                pass  # a stop interrupted this command; _AfterStop (already queued) finishes the stop
            except MarlinError as e:
                self._fail(str(e))
            except Exception as e:  # a bug in this thread must still switch the laser off (safety rule)
                self._fail(f"internal error: {e!r}")

    def _idle_wait(self):
        if self._jog:
            return self.config.jog_interval
        if self.state.state in (S.IDLE, S.PAUSED) and self.con:
            return self.config.poll_interval
        return 0.5

    def _idle_tick(self):
        if self._jog:
            axis, direction, speed = self._jog
            self._send(f"G0 {axis}{_fmt(direction * speed * self.config.jog_interval)} F{_fmt(speed * 60)}")
        elif self.state.state in (S.IDLE, S.PAUSED) and self.con:
            self._update_position()

    def _handle(self, c):
        if isinstance(c, _Shutdown):
            self._close("app exit")
            self._alive = False
        elif isinstance(c, m.Connect):
            self._connect(c)
        elif isinstance(c, m.Disconnect):
            self._close("disconnected by user")
        elif isinstance(c, m.AcknowledgeError):
            if self.state.state == S.ERROR:
                if self.con is None or self.con.lost:
                    self._close("error acknowledged, connection is gone")
                else:
                    self.state.to(S.IDLE, "error acknowledged")
        elif isinstance(c, _AfterStop):
            self._after_stop()
        elif not self._require(S.IDLE, c):
            return
        elif isinstance(c, m.Home):
            self._home(c.axes)
        elif isinstance(c, m.Jog):
            self._busy(lambda: self._jog_step(c))
        elif isinstance(c, m.JogStart):
            self._jog_start(c)
        elif isinstance(c, m.JogStop):
            self._jog_stop()
        elif isinstance(c, m.MoveTo):
            if c.frame != "relative" and not self.homed_all:
                self._log("MoveTo refused: absolute moves need homing after connect", "warning")
            else:
                self._busy(lambda: self._move_to(c))
        elif isinstance(c, m.SetWorkPosition):
            self.work_position = tuple(self.position)
            self._log(f"work position set to {self.work_position}")
            self._emit_position()
        elif isinstance(c, m.SetOutput):
            on, off = self.config.outputs[c.name]
            self._send(on if c.on else off)
        elif isinstance(c, m.StartJob):
            self._start_job(c)
        else:
            self._log(f"command {type(c).__name__} not handled", "warning")

    def _require(self, state, command):
        jog_stop_while_jogging = isinstance(command, (m.JogStop, m.JogStart)) and self.state.state == S.BUSY
        if self.state.state == state or jog_stop_while_jogging:
            return True
        self._log(f"{type(command).__name__} refused in state {self.state.state.value}", "warning")
        return False

    # ------------------------------------------------------------------ commands
    def _connect(self, c):
        if self.state.state != S.DISCONNECTED:
            self._log("already connected", "warning")
            return
        self.state.to(S.CONNECTING, f"connecting to {c.port}")
        try:
            transport = self._transport_factory(c.port, c.baudrate or self.config.baudrate)
        except TransportClosed as e:
            self.state.to(S.DISCONNECTED, f"cannot open {c.port}: {e}")
            return
        self.con = MarlinConnection(transport, on_unsolicited=lambda line: self._log(f"machine: {line}"))
        self._stop_requested.clear()
        self.homed = set()
        protocol_log.note("artisan", f"connected via {transport.name}")
        answer = self._send("M1006")
        head = self.config.toolhead_line_count.get(len(answer)) if answer and answer[0].split(":")[-1].strip() == "LASER" else None
        if head is None:
            self.toolhead = self.laser_offset = None
            self._fail(f"unknown toolhead ({len(answer)} lines from M1006) – not supported")
            return
        self.toolhead = head
        self.laser_offset = tuple(self.config.laser_offsets[head])
        self._emit(m.ToolheadDetected(head, self.laser_offset))
        self._update_position()
        self.state.to(S.IDLE, "connected – home all axes before absolute moves")

    def _home(self, axes):
        self.state.to(S.BUSY, f"homing {axes or 'all axes'}")
        self._send(f"G28 {axes}".strip(), timeout=self.config.home_timeout)
        self.homed |= set(axes.upper()) if axes else {"X", "Y", "Z"}
        self._update_position()
        self.state.to(S.IDLE, "homed")

    def _busy(self, action):
        self.state.to(S.BUSY)
        action()
        self._update_position()
        if self.state.state == S.BUSY:
            self.state.to(S.IDLE)

    def _limit(self, axis, speed):
        speed = speed or self.config.default_speed
        return min(speed, self.config.max_z_speed) if axis == "Z" else speed

    def _jog_step(self, c):
        speed = self._limit(c.axis, c.speed)
        self._send_block(["G91", f"G0 {c.axis}{_fmt(c.distance)} F{_fmt(speed * 60)}", "G90"])

    def _jog_start(self, c):
        if self._jog:
            return
        self.state.to(S.BUSY, f"jogging {c.axis}")
        self._send("G91")
        self._jog = (c.axis, 1 if c.direction > 0 else -1, self._limit(c.axis, c.speed))

    def _jog_stop(self):
        if not self._jog:
            return
        self._jog = None
        self._send("G90")
        self._update_position()
        self.state.to(S.IDLE, "jog stopped")

    def _move_to(self, c):
        speed = min(c.speed or self.config.default_speed, self.config.max_z_speed)  # v1.0 limits combined moves to the Z limit
        f = f"F{_fmt(speed * 60)}"
        if c.frame == "relative":
            self._send_block(["G91", f"G0 X{_fmt(c.x)} Y{_fmt(c.y)} Z{_fmt(c.z)} {f}", "G90"])
            return
        x, y, z = (c.x, c.y, c.z)
        if c.frame == "work":
            x, y, z = (x + self.work_position[0], y + self.work_position[1], z + self.work_position[2])
        if problem := self.outside_work_area((x, y, z)):
            self._log(f"move refused: {problem}", "error")
            return
        xy, zz = f"G0 X{_fmt(x)} Y{_fmt(y)} {f}", f"G0 Z{_fmt(z)} {f}"
        if not c.z_safe:
            moves = [f"G0 X{_fmt(x)} Y{_fmt(y)} Z{_fmt(z)} {f}"]
        elif self.position and self.position[2] < z:
            moves = [zz, xy]   # up first
        elif self.position and self.position[2] > z:
            moves = [xy, zz]   # down last
        else:
            moves = [xy]
        self._send_block(["G90"] + moves)

    def _start_job(self, c):
        runner = JobRunner(self, [JobStep.from_dict(d) for d in c.steps], self.rotary)
        problems = runner.prepare()
        if problems:
            for problem in problems:
                self._log(f"job refused: {problem}", "error")
            return
        self.state.to(S.RUNNING, "job started")
        runner.run()
        self.state.to(S.IDLE, "job finished")

    # commands while a job runs (called by the runner on this thread)
    def _next_command_nowait(self):
        return self._next_command(timeout=None)

    def _next_command(self, timeout):
        if self._stop_requested.is_set():
            raise JobCancelled()
        try:
            command = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
        except queue.Empty:
            return None
        if isinstance(command, (_AfterStop, _Shutdown)):
            self._queue.put(command)  # handled by the main loop once the job has ended
            raise JobCancelled()
        return command

    # ------------------------------------------------------------------ stop / error handling
    def _after_stop(self):
        self._stop_requested.clear()
        if self.con and not self.con.lost:
            time.sleep(0.1)  # let the acks of the stop lines arrive, then drop them as stray
            self.con.unblock()
            self._send("G90")
            self._update_position()
        if self.state.state in (S.BUSY, S.RUNNING, S.PAUSED):
            self.state.to(S.IDLE, "stopped by user")

    def _fail(self, reason):
        self._jog = None
        self._laser_off()
        self._emit(m.ErrorRaised(reason))
        protocol_log.note("artisan", f"error: {reason}")
        if self.state.state == S.ESTOP:
            return
        if self.state.can(S.ERROR):
            self.state.to(S.ERROR, reason)

    def _laser_off(self):
        con = self.con
        if con is None or con.lost:
            return
        for line in self.config.laser_off:
            try:
                con.write_now(line)  # no ack wait: must work even if the firmware stopped answering
            except ConnectionLost:
                return

    def _close(self, reason):
        self._jog = None
        if self.con:
            self._laser_off()
            time.sleep(0.05)  # let the laser-off lines leave the port before it closes
            self.con.close()
            self.con = None
        if self.state.state != S.DISCONNECTED:
            self.state.to(S.DISCONNECTED, reason)

    # ------------------------------------------------------------------ helpers
    def outside_work_area(self, point):
        """None if the machine point lies inside the configured work area, else a description."""
        for axis, value, (low, high) in zip("XYZ", point, self.config.work_area):
            if not low - 1e-6 <= value <= high + 1e-6:
                return f"{axis}{_fmt(value)} outside the work area {axis} {_fmt(low)}..{_fmt(high)}"
        return None

    def _send(self, line, timeout=None):
        if self.con is None:
            raise ConnectionLost("not connected")
        return self.con.send(line, timeout or self.config.ack_timeout)

    def _send_block(self, lines):
        for line in lines:
            if self._stop_requested.is_set():
                return
            self._send(line)

    def _update_position(self):
        answer = self._send("M114")
        for line in answer:
            if line.startswith("X:") and "Y:" in line and "Z:" in line:
                self.position = tuple(float(part.split(":")[1]) for part in line.split()[:3])
                self._emit_position()
                return

    def _emit_position(self):
        if self.position is None:
            return
        work = tuple(round(p - w, 4) for p, w in zip(self.position, self.work_position))
        self._emit(m.PositionChanged(work, tuple(self.position)))

    def _log(self, text, level="info"):
        self._emit(m.LogLine(text, level))

    def _emit(self, event):
        try:
            self.on_event(event)
        except Exception as e:  # a broken listener must not kill the machine thread
            protocol_log.note("artisan", f"event listener failed: {e!r}")

    @staticmethod
    def _default_transport(port, baudrate):
        return SimTransport() if port == SIMULATOR_PORT else SerialTransport(port, baudrate)


class _Shutdown:
    pass


class _AfterStop:
    pass
