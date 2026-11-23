"""Simulated Snapmaker Artisan (REVISION_PLAN.md P0.3 / P2.2) – the virtual machine for tests and dry runs.

Two modes:
- instant (default): every line is executed when it arrives, moves complete at once. Deterministic; used by the
  characterization tests of the old code.
- realtime: a firmware thread parses lines in order and a planner of `planner_size` blocks executes them in
  (scaled) real time. Like Marlin, a move is acknowledged when it is queued, so `ok` is delayed while the planner
  is full; `M400` answers when the planner is empty.

Laser model: modal `M3` / `M4` / `M5` with the power of the last `S` / `P`; `G0` never emits (Artisan firmware).
`laser_armed` is True while the laser would fire on the next `G1` – or at standstill in `M3` mode, which is recorded
in `standstill_emission` (worst case of C13, unless `laser_off_at_standstill=True`).

Emergency parser (`emergency_parser=True`, Marlin option): `M112` / `M410` act on arrival, even while the firmware
waits in `M400` or on a full planner. Whether the Snapmaker firmware has it is open (C15).

Faults for tests: `fail_after` (cable pulled after n lines), `drop_ack(line)`, `error_reply(line)`, `extra_lines(line)`.

Answers are modelled after Marlin and after what the current code expects. VERIFY against recorded protocol logs
(tests/HARDWARE_CHECKLIST.md section A): M114 line format, M1006 lines per toolhead, M118 echo, whether G28 clears
the G92 shift (C14).
"""
import math
import threading
import time
from collections import deque

# M1006 answers: the old code identifies the head by the first line and the total number of lines incl. "ok"
# (Artisan_Controller.get_toolhead_info: 39 -> laser1064, 34 -> laser455). Placeholder text, VERIFY.
TOOLHEAD_LINE_COUNT = {"laser1064": 39, "laser455": 34}


class SimDisconnected(Exception):
    """The simulated cable was pulled."""


class SimArtisan:
    def __init__(self, toolhead="laser1064", realtime=False, speedup=1.0, planner_size=16, laser_off_at_standstill=False,
                 emergency_parser=True):
        self.toolhead = toolhead
        self.realtime = realtime
        self.speedup = speedup
        self.planner_size = planner_size
        self.laser_off_at_standstill = laser_off_at_standstill
        self.emergency_parser = emergency_parser  # Marlin EMERGENCY_PARSER: M112 / M410 act on arrival (VERIFY C15)

        self.machine = [0.0, 0.0, 0.0]   # planned position (end of the queue) in machine coordinates – what M114 reports
        self.executed = [0.0, 0.0, 0.0]  # where the head is now (realtime mode)
        self.shift = [0.0, 0.0, 0.0]     # G92 shift: logical = machine - shift
        self.absolute = True
        self.feed = 6000.0               # mm/min, modal
        self.laser_mode = None           # "M3" / "M4" / None
        self.laser_power = 0.0           # last S (0..255) or P (percent)
        self.halted = False
        self.dead = False

        self.fail_after = None
        self.drop_ack = None
        self.error_reply = None
        self.extra_lines = None

        self.trace = []                  # (thread name, line) of every line received from the host
        self.standstill_emission = []    # times at which M3 kept the laser on with nothing moving
        self.idle_gaps = 0.0             # s the head stood still between two blocks (planner starvation, sync points)
        self.blocks_executed = 0
        self.moves = []                  # (code, machine position after the line, laser would emit) per G0 / G1

        self._out = deque()
        self._lock = threading.Condition()
        self._input = deque()
        self._planner = deque()
        self._busy_block = False
        self._abort_block = False
        self._block = None
        self._last_block_end = None
        self._stop = False
        if realtime:
            threading.Thread(target=self._firmware_loop, name="sim-firmware", daemon=True).start()
            threading.Thread(target=self._executor_loop, name="sim-planner", daemon=True).start()

    # ------------------------------------------------------------------ host side
    def receive(self, line):
        with self._lock:
            if self.dead:
                raise SimDisconnected()
            self.trace.append((threading.current_thread().name, line))
            if self.fail_after is not None and len(self.trace) > self.fail_after:
                self.dead = True
                raise SimDisconnected()
            if self.halted:
                return
            if self.realtime:
                code = line.split(";")[0].strip().upper().split(" ")[0] if line.strip() else ""
                if self.emergency_parser and code in ("M112", "M410"):
                    self._execute(code)  # acts at once, even while the firmware waits in M400 or on a full planner
                    if code == "M112":
                        return
                self._input.append(line)
                self._lock.notify_all()
            else:
                self._answer(line, self._execute(line))

    def readline(self, wait=0.001):
        with self._lock:
            if self.dead:
                raise SimDisconnected()
            if not self._out:
                self._lock.wait(wait)
            if self._out:
                return self._out.popleft()
        return ""

    def close(self):
        with self._lock:
            self._stop = True
            self._lock.notify_all()

    @property
    def laser_armed(self):
        return self.laser_mode is not None and self.laser_power > 0 and not self.halted

    def logical(self):
        return [m - s for m, s in zip(self.machine, self.shift)]

    # ------------------------------------------------------------------ firmware (called with the lock held)
    def _answer(self, line, answers):
        if self.drop_ack and self.drop_ack(line):
            answers = [a for a in answers if a != "ok"]
        if self.error_reply and (err := self.error_reply(line)):
            answers = [err]
        if self.extra_lines:
            answers = list(self.extra_lines(line)) + answers
        self._out.extend(answers)
        self._lock.notify_all()

    def _words(self, line):
        words = {}
        for part in line.split(";")[0].split()[1:]:
            letter = part[0].upper()
            if letter in "XYZFSP":
                try:
                    words[letter] = float(part[1:])
                except ValueError:
                    pass
        return words

    def _execute(self, line):
        """Parse one line, update the planned state, return the answer lines. In realtime mode motion is queued."""
        parts = line.split(";")[0].split()
        code = parts[0].upper() if parts else ""
        words = self._words(line)
        if code in ("G0", "G1"):
            start = list(self.machine)
            for axis in "XYZ":
                if axis in words:
                    i = "XYZ".index(axis)
                    target = words[axis] if self.absolute else self.logical()[i] + words[axis]
                    self.machine[i] = target + self.shift[i]
            if "F" in words:
                self.feed = words["F"]
            if code == "G1":
                if "S" in words:
                    self.laser_power = words["S"]
                elif "P" in words:
                    self.laser_power = words["P"]
            self.moves.append((code, tuple(self.machine), code == "G1" and self.laser_armed))
            if self.realtime:
                duration = math.dist(start, self.machine) / self.feed * 60 if self.feed > 0 else 0.0
                self._queue(duration, list(self.machine), emits=(code == "G1" and self.laser_armed))
            return ["ok"]
        if code == "G4":
            if self.realtime:
                self._queue(words.get("P", 0) / 1000 + words.get("S", 0), list(self.machine), emits=False)
            return ["ok"]
        if code == "G90":
            self.absolute = True
            return ["ok"]
        if code == "G91":
            self.absolute = False
            return ["ok"]
        if code == "G92":
            for axis in "XYZ":
                if axis in words:
                    i = "XYZ".index(axis)
                    self.shift[i] = self.machine[i] - words[axis]
            return ["ok"]
        if code == "G28":
            axes = [a for a in "XYZ" if a in line.upper()[3:]] or list("XYZ")
            for a in axes:
                i = "XYZ".index(a)
                self.machine[i] = 0.0
                self.shift[i] = 0.0  # VERIFY (C14): assumes homing clears the G92 shift
            if self.realtime:
                self._queue(0.0, list(self.machine), emits=False)
            return ["ok"]
        if code in ("M3", "M4"):
            self.laser_mode = code
            if "S" in words:
                self.laser_power = words["S"]
            elif "P" in words:
                self.laser_power = words["P"]
            return ["ok"]
        if code == "M5":
            self.laser_mode = None
            return ["ok"]
        if code == "M114":
            x, y, z = self.logical()
            return [f"X:{x:.2f} Y:{y:.2f} Z:{z:.2f} A:0.000 B:0.000 E:0.00 Count X: 0 Y: 0 Z: 0 A:0 B:0", "ok"]
        if code == "M1006":
            n = TOOLHEAD_LINE_COUNT[self.toolhead]
            return ["Tool Head: LASER"] + [f"info{i}: placeholder" for i in range(n - 2)] + ["ok"]
        if code == "M118":
            return [line.split(None, 1)[1] if " " in line else "", "ok"]
        if code in ("M112", "M410"):
            self._planner.clear()
            if self.realtime:
                self.executed = self._head_position()
                self.machine = list(self.executed)
                self._abort_block = True
            if code == "M112":
                self.halted = True
                self.laser_mode = None
                return []
            return ["ok"]
        if not (code[:1] in ("G", "M") and code[1:].isdigit()):
            return [f'echo:Unknown command: "{line}"', "ok"]
        return ["ok"]  # M8/M9, M400 (instant mode), M2000, ...

    def _head_position(self):
        """Where the head is right now: interpolated inside the running block."""
        if self._block is None:
            return list(self.executed)
        start, target, t0, t1 = self._block
        progress = 1.0 if t1 <= t0 else min(1.0, (time.time() - t0) / (t1 - t0))
        return [s + (t - s) * progress for s, t in zip(start, target)]

    def _queue(self, duration, target, emits):
        while len(self._planner) + self._busy_block >= self.planner_size and not self._stop and not self.halted:
            self._lock.wait(0.05)  # planner full: Marlin stops reading the serial buffer, the ok is delayed
        self._planner.append((duration, target, emits))
        self._lock.notify_all()

    def _firmware_loop(self):
        with self._lock:
            while not self._stop:
                if not self._input:
                    self._lock.wait(0.05)
                    continue
                line = self._input.popleft()
                if self.halted:
                    continue
                if line.split(";")[0].strip().upper().startswith("M400"):
                    while (self._planner or self._busy_block) and not self._stop and not self.halted:
                        self._lock.wait(0.01)
                    self._answer(line, ["ok"])
                    continue
                self._answer(line, self._execute(line))

    def _executor_loop(self):
        while True:
            with self._lock:
                while not self._planner and not self._stop:
                    if self.laser_mode == "M3" and self.laser_power > 0 and not self.laser_off_at_standstill and not self.halted:
                        if not self.standstill_emission or time.time() - self.standstill_emission[-1] > 0.05:
                            self.standstill_emission.append(time.time())
                    self._lock.wait(0.01)
                if self._stop:
                    return
                duration, target, emits = self._planner.popleft()
                self._busy_block = True
                self._abort_block = False
                now = time.time()
                if self._last_block_end is not None:  # time the head stood still between two blocks
                    self.idle_gaps += max(0.0, now - self._last_block_end)
                # run the block; M410 / M112 interrupt it where the head is (see _head_position)
                end = now + duration / self.speedup
                self._block = (list(self.executed), target, now, end)
                while not self._abort_block and not self._stop and time.time() < end:
                    self._lock.wait(min(0.01, max(0.0, end - time.time())))
                if not self._abort_block:
                    self.executed = target
                self._block = None
                self.blocks_executed += 1
                self._busy_block = False
                self._last_block_end = time.time()
                self._lock.notify_all()
