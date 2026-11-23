"""Simulated Snapmaker Artisan: a fake `serial.Serial` that answers like the Marlin firmware (REVISION_PLAN.md P0.3).

Answers are modelled after Marlin and after what the current code expects. VERIFY against recorded protocol logs
(P0.2) and replace by the recorded text where it differs: M114 line format, M1006 lines per toolhead, M118 echo
(with or without "echo:"), whether G28 clears the G92 shift.

Moves complete instantly; positions are exact. Every line written is recorded in `trace` with its thread name,
so tests can pin what the application sends.
"""
import threading
import time
from collections import deque

# M1006 answers: the current code identifies the head by the first line and the total number of lines incl. "ok"
# (Artisan_Controller.get_toolhead_info: 39 -> laser1064, 34 -> laser455). Placeholder text, VERIFY.
TOOLHEAD_LINE_COUNT = {"laser1064": 39, "laser455": 34}


class SimArtisan:
    """Firmware state shared by the fake port. One instance per test."""

    def __init__(self, toolhead="laser1064"):
        self.toolhead = toolhead
        self.machine = [0.0, 0.0, 0.0]   # machine coordinates
        self.shift = [0.0, 0.0, 0.0]     # G92 shift: logical = machine - shift
        self.absolute = True
        self.halted = False
        self.trace = []                  # (thread name, line) of every line received from the host
        self._out = deque()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ host side (called by FakeSerial)
    def receive(self, line):
        with self._lock:
            self.trace.append((threading.current_thread().name, line))
            if self.halted:
                return
            for answer in self._execute(line):
                self._out.append(answer)

    def readline(self):
        with self._lock:
            if self._out:
                return self._out.popleft()
        time.sleep(0.001)  # real port: blocks up to its timeout; keep timeouts in tests short instead
        return ""

    # ------------------------------------------------------------------ firmware
    def logical(self):
        return [m - s for m, s in zip(self.machine, self.shift)]

    def _words(self, line):
        words = {}
        for part in line.split()[1:]:
            if part[0].upper() in "XYZ":
                words[part[0].upper()] = float(part[1:])
        return words

    def _execute(self, line):
        code = line.split()[0].upper() if line.split() else ""
        if code in ("G0", "G1"):
            for axis, value in self._words(line).items():
                i = "XYZ".index(axis)
                target = value if self.absolute else self.logical()[i] + value
                self.machine[i] = target + self.shift[i]
            return ["ok"]
        if code == "G90":
            self.absolute = True
            return ["ok"]
        if code == "G91":
            self.absolute = False
            return ["ok"]
        if code == "G92":
            for axis, value in self._words(line).items():
                i = "XYZ".index(axis)
                self.shift[i] = self.machine[i] - value
            return ["ok"]
        if code == "G28":
            axes = [a for a in "XYZ" if a in line.upper()[3:]] or list("XYZ")
            for a in axes:
                i = "XYZ".index(a)
                self.machine[i] = 0.0
                self.shift[i] = 0.0  # VERIFY: the app assumes homing clears the G92 shift
            return ["ok"]
        if code == "M114":
            x, y, z = self.logical()
            return [f"X:{x:.2f} Y:{y:.2f} Z:{z:.2f} A:0.000 B:0.000 E:0.00 Count X: 0 Y: 0 Z: 0 A:0 B:0", "ok"]
        if code == "M1006":
            n = TOOLHEAD_LINE_COUNT[self.toolhead]
            return ["Tool Head: LASER"] + [f"info{i}: placeholder" for i in range(n - 2)] + ["ok"]
        if code == "M118":
            return [line.split(None, 1)[1] if " " in line else "", "ok"]
        if code == "M112":
            self.halted = True
            return []
        if not (code[:1] in ("G", "M") and code[1:].isdigit()):
            return [f'echo:Unknown command: "{line}"', "ok"]
        return ["ok"]  # M3/M4/M5, M8/M9, M400, M2000, G4, ...


class FakeSerial:
    """Drop-in for `serial.Serial` as used by Artisan_Controller (write / readline / is_open / close)."""

    def __init__(self, sim, port=None, baudrate=None, timeout=1):
        self.sim = sim
        self.port = port
        self.is_open = True

    def write(self, data):
        for line in data.decode().splitlines():
            self.sim.receive(line)
        return len(data)

    def readline(self):
        return (self.sim.readline() + "\n").encode() if self.is_open else b""

    def close(self):
        self.is_open = False


class FakeRotMotors:
    """Stand-in for RotMotorCotroller in job tests: records moves into the same trace."""

    def __init__(self, sim, motor_ids=(1,)):
        self.sim = sim
        self.motors = []
        self.angles = {i: 0.0 for i in motor_ids}

    def move_to_angle(self, sid, angle, wait_for_position=False):
        self.angles[sid] = angle
        self.sim.trace.append((threading.current_thread().name, f"<rotary {sid} -> {angle:g} deg wait={wait_for_position}>"))

    def get_current_angle(self, sid):
        return [self.angles[sid]]
