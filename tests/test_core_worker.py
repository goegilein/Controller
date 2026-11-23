"""P2.3: the machine worker on the realtime simulator – safety rules as scenarios."""
import threading
import time

import pytest

from machine_core import messages as m
from machine_core.sim import SimArtisan
from machine_core.transport import SimTransport
from machine_core.worker import ArtisanConfig, MachineWorker


def wait_for(predicate, timeout=3.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timeout waiting for {what}")


class Rig:
    def __init__(self, toolhead="laser1064", speedup=20, realtime=True, rotary=None, **config):
        self.sim = SimArtisan(toolhead=toolhead, realtime=realtime, speedup=speedup)
        self.events = []
        self._lock = threading.Lock()
        self.worker = MachineWorker(on_event=self._on_event, config=ArtisanConfig(**config),
                                    transport_factory=lambda port, baud: SimTransport(self.sim), rotary=rotary)

    def _on_event(self, event):
        with self._lock:
            self.events.append(event)

    @property
    def state(self):
        return self.worker.state.state.value

    def of(self, cls):
        with self._lock:
            return [e for e in self.events if isinstance(e, cls)]

    def sent(self):
        return [line for _, line in self.sim.trace]

    def submit_and_wait(self, command, state="idle", timeout=3.0):
        self.worker.submit(command)
        time.sleep(0.05)
        wait_for(lambda: self.state == state and self.worker._queue.empty(), timeout, f"state {state}")

    def connect(self, home=True):
        self.submit_and_wait(m.Connect("simulator"))
        if home:
            self.submit_and_wait(m.Home())

    def close(self):
        self.worker.shutdown()
        self.sim.close()


@pytest.fixture
def rig():
    r = Rig()
    yield r
    r.close()


def test_connect_detects_toolhead_and_never_sends_g92(rig):
    rig.connect()
    assert rig.of(m.ToolheadDetected)[0] == m.ToolheadDetected("laser1064", (21.3, -11.3, 0.0))
    assert rig.sent().count("M1006") == 1
    assert [e.state for e in rig.of(m.StateChanged)][:2] == ["connecting", "idle"]
    rig.submit_and_wait(m.SetWorkPosition())
    assert not any(line.startswith("G92") for line in rig.sent())


def test_unknown_toolhead_is_an_error_not_a_test_mode():
    """B08: no "TEST" fallback – an unknown head leaves the machine in error, jobs cannot start."""
    rig = Rig()
    rig.sim.toolhead = "laser455"
    rig.worker.config.toolhead_line_count = {39: "laser1064"}
    rig.worker.submit(m.Connect("simulator"))
    wait_for(lambda: rig.state == "error", what="error")
    assert "unknown toolhead" in rig.of(m.ErrorRaised)[0].message
    rig.close()


def test_absolute_move_refused_before_homing(rig):
    rig.connect(home=False)
    rig.submit_and_wait(m.MoveTo(10, 10, 0))
    assert not any(line.startswith("G0 X10") for line in rig.sent())
    assert any("need homing" in e.text for e in rig.of(m.LogLine))


def test_move_to_is_z_safe_and_in_machine_coordinates(rig):
    rig.connect()
    rig.submit_and_wait(m.MoveTo(100, 50, 20, speed=30))
    rig.submit_and_wait(m.MoveTo(120, 60, 5, speed=30))
    sent = rig.sent()
    i = sent.index("G0 Z20 F1800")
    assert sent[i + 1] == "G0 X100 Y50 F1800"                      # up first
    j = sent.index("G0 X120 Y60 F1800")
    assert sent[j + 1] == "G0 Z5 F1800"                            # down last
    assert rig.worker.position == (120.0, 60.0, 5.0)
    rig.submit_and_wait(m.SetWorkPosition())
    rig.submit_and_wait(m.MoveTo(1, 2, 0, frame="work"))
    assert "G0 X121 Y62 F1800" in rig.sent()
    assert rig.of(m.PositionChanged)[-1] == m.PositionChanged((1.0, 2.0, 0.0), (121.0, 62.0, 5.0))


def test_jog_sequence_is_atomic(rig):
    """B11: G91 / G0 / G90 go out in one piece even if other commands are queued right behind."""
    rig.connect()
    for _ in range(3):
        rig.worker.submit(m.Jog("X", 1.5, 20))
        rig.worker.submit(m.MoveTo(0, 0, 0, frame="relative"))
    rig.submit_and_wait(m.SetOutput("light", True))
    sent = rig.sent()
    for i, line in enumerate(sent):
        if line == "G91":
            assert sent[i + 2] == "G90", sent[i:i + 3]


def test_continuous_jog_stops_promptly(rig):
    rig.connect()
    rig.worker.submit(m.JogStart("Y", 1, 20))
    time.sleep(0.5)
    rig.submit_and_wait(m.JogStop())
    y = rig.worker.position[1]
    assert 0.5 * 20 * 0.5 < y < 2.0 * 20 * 0.5                     # moved for about the time the button was held
    time.sleep(0.3)
    assert rig.sim.executed[1] == pytest.approx(y, abs=1e-6)        # nothing left in the planner


def test_submit_never_blocks_the_caller(rig):
    rig.connect()
    rig.sim.drop_ack = lambda line: line.startswith("G28")
    t0 = time.monotonic()
    rig.worker.submit(m.Home())
    rig.worker.submit(m.SetOutput("fan", True))
    assert time.monotonic() - t0 < 0.01


def test_stop_quick_stops_and_switches_the_laser_off(rig):
    rig.connect()
    rig.sim.speedup = 1
    rig.worker.submit(m.MoveTo(300, 300, 0, speed=30))              # ~14 s at real speed
    # the ok comes when the move is queued, so the worker is idle again while the head still moves (as in v1.0)
    wait_for(lambda: rig.sim._block is not None and rig.sim._block[1][0] == 300, what="head moving")
    time.sleep(0.2)
    rig.worker.submit(m.Stop())
    wait_for(lambda: rig.state == "idle" and rig.worker._queue.empty(), what="idle after stop")
    time.sleep(0.2)
    sent = rig.sent()
    assert sent.index("M410") < sent.index("M5")
    assert 0 < rig.worker.position[0] < 50
    assert rig.sim.executed[0] == pytest.approx(rig.worker.position[0], abs=0.01)  # M114 has 2 decimals


def test_no_line_slips_in_behind_a_stop(rig):
    """A stop that races with a command being sent: nothing of that command may reach the machine after M410."""
    rig.connect()
    rig.sim.speedup = 1
    for i in range(10):
        rig.worker.submit(m.MoveTo(200 + i, 200, 0, speed=30))
        time.sleep(0.002 * i)
        rig.worker.submit(m.Stop())
        wait_for(lambda: rig.state == "idle" and rig.worker._queue.empty(), what="idle after stop")
        sent = rig.sent()
        after_stop = sent[len(sent) - sent[::-1].index("M410"):]
        assert not any(line.startswith("G0 X2") for line in after_stop), after_stop


def test_emergency_stop_halts_and_needs_reconnect(rig):
    rig.worker.config.ack_timeout = 0.3
    rig.connect()
    rig.sim.laser_mode, rig.sim.laser_power = "M3", 100             # pretend a job left the laser armed
    rig.worker.submit(m.EmergencyStop())
    wait_for(lambda: rig.sim.halted, what="firmware halt")
    assert rig.state == "estop" and not rig.sim.laser_armed
    rig.submit_and_wait(m.Home(), state="estop")                    # refused
    rig.submit_and_wait(m.Disconnect(), state="disconnected")
    rig.submit_and_wait(m.Connect("simulator"), state="error")      # same halted firmware: no answer -> error, not idle


def test_lost_connection_is_an_error_and_nothing_resumes(rig):
    rig.connect()
    rig.sim.fail_after = len(rig.sim.trace) + 2                     # cable pulled during idle polling
    wait_for(lambda: rig.state == "error", what="error")
    assert "connection lost" in rig.of(m.ErrorRaised)[0].message
    rig.submit_and_wait(m.Home(), state="error")                    # refused until acknowledged
    rig.submit_and_wait(m.AcknowledgeError(), state="disconnected")


def test_ack_timeout_switches_the_laser_off(rig):
    rig.worker.config.ack_timeout = 0.3
    rig.connect()
    rig.sim.drop_ack = lambda line: line.startswith("G0")
    rig.worker.submit(m.Jog("X", 1, 10))
    wait_for(lambda: rig.state == "error", what="error")
    assert rig.sent()[-2:] == ["M5", "M9"]
    rig.sim.drop_ack = None
    rig.submit_and_wait(m.AcknowledgeError())


def test_exception_in_the_worker_switches_the_laser_off(rig, monkeypatch):
    rig.connect()
    monkeypatch.setattr(rig.worker, "_move_to", lambda c: 1 / 0)
    rig.worker.submit(m.MoveTo(1, 1, 1))
    wait_for(lambda: rig.state == "error", what="error")
    assert "internal error" in rig.of(m.ErrorRaised)[0].message
    assert rig.sent()[-2:] == ["M5", "M9"]


def test_shutdown_switches_the_laser_off():
    rig = Rig()
    rig.connect()
    rig.worker.shutdown()
    assert rig.sent()[-2:] == ["M5", "M9"] and rig.state == "disconnected"
    rig.sim.close()


def test_coordinates_without_float_noise(rig):
    """B25."""
    rig.connect()
    rig.submit_and_wait(m.MoveTo(0.1 + 0.2, 21.3 - 42.6 + 21.3, 0))
    assert "G0 X0.3 Y0 F1800" in rig.sent()
