"""P2.8: Qt bridge and the facades with the old controller API, on the simulated Artisan."""
import threading
import time

import pytest
from PyQt6 import QtWidgets

from machine_bridge import ArtisanFacade, MachineBridge, RotaryFacade
from machine_core.job import JobStep, step_transform
from machine_core import messages as m
from machine_core.sim import SimArtisan
from machine_core.transport import SimTransport
from test_core_job import JOBS


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(predicate, timeout=5.0, what="condition"):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"timeout waiting for {what}")


class Setup:
    def __init__(self, home=True):
        self.sim = SimArtisan(realtime=True, speedup=20)
        self.bridge = MachineBridge(transport_factory=lambda port, baud: SimTransport(self.sim))
        self.asked = []
        self.ac = ArtisanFacade(self.bridge, ask_home=lambda: self.asked.append(1) or home)
        self.ac.port = "simulator"

    def sent(self):
        return [line for _, line in self.sim.trace]

    def settle(self):
        pump(lambda: self.bridge.worker.state.state.value == "idle" and self.bridge.worker._queue.empty(), what="idle")
        time.sleep(0.05)
        pump(lambda: self.bridge.worker._queue.empty())

    def close(self):
        self.bridge.shutdown()
        self.sim.close()


@pytest.fixture
def setup(qapp):
    s = Setup()
    s.ac.connect()
    pump(lambda: s.bridge.worker.homed_all, what="homed")
    s.settle()
    yield s
    s.close()


def test_connect_asks_for_homing_and_events_arrive_in_the_ui_thread(qapp):
    s = Setup()
    threads = set()
    s.ac.add_position_changed_callback(lambda pos: threads.add(threading.current_thread().name))
    s.ac.connect()
    pump(lambda: s.bridge.worker.homed_all, what="homed")
    s.settle()
    pump(lambda: threads, what="position")
    assert s.asked == [1] and s.ac.tool_head == "laser1064" and s.ac.laser_offset == [21.3, -11.3, 0.0]
    assert threads == {"MainThread"}                                      # B07
    assert s.ac.get_absolute_position() == [0.0, 0.0, 0.0] and s.ac.is_connection_active()
    s.close()


def test_no_homing_if_declined(qapp):
    s = Setup(home=False)
    s.ac.connect()
    pump(lambda: s.asked, what="question")
    s.settle()
    assert "G28" not in s.sent() and not s.ac.is_homed
    s.close()


def test_position_reads_do_no_io(setup):
    n = len(setup.sim.trace)
    for _ in range(50):
        setup.ac.get_absolute_position(), setup.ac.get_position()
    assert len(setup.sim.trace) - n < 5                                   # only the worker's idle polling (B12)


def test_old_api_maps_to_commands(setup):
    ac = setup.ac
    ac.move_axis_absolute(100, 50, 20, speed=30)
    setup.settle()
    ac.set_work_position()
    setup.settle()
    ac.move_axis_to("absolute", 1, 2, 0)                                  # work frame, one G0 (v1.0)
    ac.move_axis_to("relative", 0.5, 0, 0, speed=10)
    ac.move_to_work_position()
    ac.move_axis_step("X", -1, 2, 5)
    ac.home_axis(False)                                                   # what clicked() passes
    for setter in (ac.set_laser_crosshair, ac.set_air_assist):
        setter("on")
        setter("off")
    setup.settle()
    sent = setup.sent()
    i = sent.index("G0 Z20 F1800")
    assert sent[i + 1] == "G0 X100 Y50 F1800"                             # Z-safe: up first
    assert "G0 X101 Y52 Z20 F1800" in sent
    assert "G0 X0.5 Y0 Z0 F600" in sent and "G0 X100 Y50 Z20 F1800" in sent
    assert "G0 X-2 F300" in sent and "G28" in sent
    assert all(line in sent for line in ("M2000 L13 P1", "M2000 L13 P0", "M8", "M9"))
    assert not any(line.startswith("G92") for line in sent)


def test_process_state_and_progress_in_the_ui_thread(setup):
    states, threads = [], set()
    setup.ac.set_process_state_callback(lambda st: (states.append(st), threads.add(threading.current_thread().name)))
    setup.bridge.submit(m.StartJob((JobStep("s", str(JOBS / "long_moves.nc"), step_transform(100, 100, 0)).to_dict(),)))
    pump(lambda: states[-2:] == ["Running", "Idle"], timeout=20, what="job done")
    assert threads == {"MainThread"}


def test_stop_and_emergency_stop(setup):
    errors = []
    setup.ac.error_callbacks.append(errors.append)
    setup.ac.move_axis_absolute(300, 300, 0, speed=5)
    pump(lambda: setup.sim._block is not None, what="moving")
    setup.ac.stop()
    setup.settle()
    assert "M410" in setup.sent()
    setup.ac.emergency_stop()
    pump(lambda: setup.ac.state == "estop", what="estop")
    assert setup.sim.halted and setup.ac.process_state == "Idle"


# --------------------------------------------------------------------------- rotary facade

def test_rotary_facade_simulator(qapp):
    rot = RotaryFacade()
    rot.port = "simulator"
    seen, logs = [], []
    rot.set_connected_callback(seen.append)
    rot.set_log_callback(logs.append)
    rot.connect()
    assert seen == [True] and rot.get_motor_ids() == [1, 2] and rot.is_connection_active()
    assert rot.move_to_angle(7, 10) is False and "no rotary motor 7" in logs[-1]    # a click never raises
    assert rot.move_to_angle(1, 5, wait_for_position=True, timeout=30) is True
    bus = rot.bus
    rot.disconnect()
    assert seen == [True, False] and bus.last_speed(1) == 0 and bus.last_speed(2) == 0


def test_rotary_facade_connect_error_is_logged(qapp):
    def broken():
        raise OSError("no such port")
    rot = RotaryFacade(bus_factory=broken)
    logs = []
    rot.set_log_callback(logs.append)
    rot.connect()
    assert not rot.connected and "no such port" in logs[-1]
