"""Test adapters around the simulated Artisan (machine_core/sim.py) for the old code (characterization tests)."""
import threading

from machine_core.sim import SimArtisan  # noqa: F401  (re-exported for the tests)


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
