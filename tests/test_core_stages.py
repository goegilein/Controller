"""P2.7: rotary stages on a simulated servo bus – B06 (motors must never keep spinning), timeouts, 3:1 (C8)."""
import time

import pytest

from machine_core import messages as m
from machine_core.job import JobStep, step_transform
from machine_core.stages import TICKS_PER_REV, RotaryStages, SimStageBus, StageError, StageTimeout
from test_core_job import JOBS
from test_core_worker import Rig, wait_for


def make_stages(ids=(1,), **kw):
    bus = SimStageBus(ids)
    stages = RotaryStages(lambda: bus, **kw)
    stages.connect()
    return stages, bus


@pytest.fixture
def stages():
    s, bus = make_stages(ids=(1, 2))
    yield s, bus
    s.disconnect()


def test_connect_and_move_with_gear_ratio_3(stages):
    s, bus = stages
    assert [mo.ID for mo in s.motors] == [1, 2] and bus.wheel_mode == {1, 2}
    assert s.move_to_angle(1, 20, wait_for_position=True, timeout=10) is True
    assert bus.motors[1]["pos"] == pytest.approx(20 * 3 / 360 * TICKS_PER_REV, abs=4)   # 3:1 (C8)
    assert s.get_current_angle(1)[0] == pytest.approx(20, abs=0.2)
    assert bus.motors[2]["pos"] == 0


def test_wait_does_not_return_before_the_move_started(stages):
    """v1.0 slept 0.1 s and hoped the loop had cleared position_reached by then."""
    s, bus = stages
    with s.lock:                                                      # the control loop cannot run in between
        s.move_to_angle(1, 10)
        assert not s.motors[0].position_reached


def test_stop_motor_really_stops(stages):
    """v1.0 wrote speed 0 but kept the target, so the control loop drove on 20 ms later."""
    s, bus = stages
    s.move_to_angle(1, 360)
    time.sleep(0.3)
    s.stop_motor(1)
    time.sleep(0.5)
    pos = bus.motors[1]["pos"]
    time.sleep(0.3)
    assert abs(bus.motors[1]["pos"] - pos) < 5 and bus.last_speed(1) == 0
    assert s.get_current_angle(1)[0] < 100


def test_disconnect_stops_every_motor(stages):
    s, bus = stages
    s.move_to_angle(-1, 360)
    time.sleep(0.2)
    s.disconnect()
    assert bus.last_speed(1) == 0 and bus.last_speed(2) == 0 and bus.closed
    n = len(bus.writes)
    time.sleep(0.1)
    assert len(bus.writes) == n                                       # the loop has ended


def test_failed_reads_stop_the_motors_and_fault(stages):
    s, bus = stages
    s.move_to_angle(1, 360)
    time.sleep(0.2)
    bus.fail_reads.add(1)
    wait_for(lambda: s.fault is not None, what="fault")
    assert bus.last_speed(1) == 0 and bus.last_speed(2) == 0
    with pytest.raises(StageError, match="reconnect"):
        s.move_to_angle(1, 0, wait_for_position=True)


def test_exception_in_the_loop_stops_the_motors(stages):
    """B06: v1.0's dummy read was outside the try – the thread died and the last speed stayed active."""
    s, bus = stages
    s.move_to_angle(2, 360)
    time.sleep(0.2)
    bus.raise_on_read = True
    wait_for(lambda: s.fault is not None, what="fault")
    assert "simulated bus error" in s.fault and bus.last_speed(2) == 0


def test_wait_times_out_and_stops_the_motor(stages):
    s, bus = stages
    bus.jammed.add(1)
    t0 = time.monotonic()
    with pytest.raises(StageTimeout):
        s.move_to_angle(1, 90, wait_for_position=True, timeout=0.5)
    assert time.monotonic() - t0 < 1.0
    assert bus.last_speed(1) == 0 and s.motors[0].position_reached


def test_wait_can_be_cancelled(stages):
    s, bus = stages
    bus.jammed.add(1)
    t0 = time.monotonic()
    assert s.move_to_angle(1, 90, wait_for_position=True, cancel=lambda: time.monotonic() - t0 > 0.2) is False
    assert bus.last_speed(1) == 0


# --------------------------------------------------------------------------- with the machine worker

def rotary_job(tmp_path):
    jcode = tmp_path / "job.jcode"
    jcode.write_text(f"J0 X0 Y0 Z0 R90\nJ1 {JOBS / 'long_moves.nc'}\n", encoding="utf-8")
    return m.StartJob((JobStep("s", str(jcode), step_transform(100, 100, 0), rot_motor_id=1).to_dict(),))


def test_stop_during_a_rotary_move_ends_the_job_and_stops_the_stage(tmp_path):
    stages, bus = make_stages()
    bus.jammed.add(1)
    rig = Rig(rotary=stages)
    rig.connect()
    rig.worker.submit(rotary_job(tmp_path))
    wait_for(lambda: rig.state == "running" and bus.last_speed(1), what="rotary turning")
    rig.worker.submit(m.Stop())
    wait_for(lambda: rig.state == "idle" and rig.worker._queue.empty(), what="idle after stop")
    assert bus.last_speed(1) == 0
    assert not any(line.startswith("G1") for line in rig.sent())      # nothing burned
    rig.close()
    stages.disconnect()


def test_rotary_timeout_in_a_job_is_an_error_with_the_laser_off(tmp_path):
    stages, bus = make_stages(move_timeout=0.5)
    bus.jammed.add(1)
    rig = Rig(rotary=stages)
    rig.connect()
    rig.worker.submit(rotary_job(tmp_path))
    wait_for(lambda: rig.state == "error", timeout=5, what="error")
    assert "rotary stage" in rig.of(m.ErrorRaised)[0].message
    assert rig.sent()[-2:] == ["M5", "M9"] and bus.last_speed(1) == 0
    rig.close()
    stages.disconnect()
