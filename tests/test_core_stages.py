"""P2.7: rotary stages on a simulated servo bus – B06 (motors must never keep spinning), timeouts, 3:1 (C8)."""
import time

import pytest

from machine_core import messages as m
from machine_core.job import JobStep, step_transform
from machine_core.stages import TICKS_PER_REV, RotaryStages, SimStageBus, StageError, StageTimeout
from test_core_job import JOBS
from test_core_worker import Rig, wait_for


def make_stages(ids=(1,), **kw):
    bus = SimStageBus(ids, cycle_dt=0.02)
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
    assert s.move_to_angle(1, 20, wait_for_position=True, timeout=30) is True
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


def test_a_broken_position_display_does_not_stop_the_control(stages):
    s, bus = stages
    s.motors[0].set_position_changed_callback(lambda deg: 1 / 0)
    assert s.move_to_angle(1, 10, wait_for_position=True, timeout=30) is True and s.fault is None


def test_gear_ratio_per_motor():
    """5:1 upgrade of one stage: the ratio is set per motor id (settings rotary_motors.gear_ratios)."""
    bus = SimStageBus((1, 2), cycle_dt=0.02)
    s = RotaryStages(lambda: bus, gear_ratios={2: 5})
    s.connect()
    assert [mo.gear_ratio for mo in s.motors] == [3, 5]
    assert s.motors[1].ticks(360) == 5 * TICKS_PER_REV
    s.disconnect()


# --------------------------------------------------------------------------- C16: the servo's own position loop

@pytest.fixture
def pstages():
    s, bus = make_stages(ids=(1, 2), control_mode="position")
    for motor in s.motors:
        motor.speed_limit = 3000                                              # short tests; v1.0 default is 1000
    yield s, bus
    s.disconnect()


def test_position_mode_reaches_the_tick_over_several_turns(pstages):
    """Full 360° on the part = 3 motor turns at 3:1; the servo positions itself, the PC only writes the goal."""
    s, bus = pstages
    assert bus.position_mode == {1, 2} and not bus.wheel_mode
    assert s.move_to_angle(1, 360, wait_for_position=True, timeout=30) is True
    assert bus.motors[1]["pos"] == 3 * TICKS_PER_REV and bus.last_goal(1) == 3 * TICKS_PER_REV
    assert s.get_current_angle(1)[0] == 360
    assert s.move_to_angle(1, -45.1, wait_for_position=True, timeout=30) is True
    assert bus.motors[1]["pos"] == s.motors[0].ticks(-45.1)                    # on the tick, not ±3
    goals = [w for _, i, w in bus.writes if i == 1 and isinstance(w, tuple)]
    assert len(goals) == 3                                                    # hold at connect + one per target
    assert bus.last_speed(1) is None                                          # no wheel speeds at all


def test_position_mode_refuses_targets_outside_the_servo_range(pstages):
    s, bus = pstages
    with pytest.raises(StageError, match="outside the servo range"):
        s.move_to_angle(1, 1000)                                              # 1000° × 3 turns > ±30000 ticks
    assert s.move_to_angle(1, -870) is True                                   # just inside


def test_position_mode_stop_holds_where_the_stage_is(pstages):
    s, bus = pstages
    s.move_to_angle(1, 360)
    time.sleep(0.5)
    s.stop_motor(1)
    time.sleep(1.5)
    pos = bus.motors[1]["pos"]
    time.sleep(0.3)
    assert bus.motors[1]["pos"] == pos and 0 < pos < 3 * TICKS_PER_REV
    assert abs(bus.last_goal(1) - pos) < 200                                  # goal := present position


def test_position_mode_disconnect_leaves_the_servo_holding(pstages):
    s, bus = pstages
    s.move_to_angle(-1, 90)
    time.sleep(0.2)
    s.disconnect()
    assert bus.closed and bus.last_goal(1) is not None and not bus.released


def test_position_mode_without_full_angle_feedback_releases_the_torque():
    """If the servo reported single-turn positions, the PC's ticks and the servo's goals would differ by turns."""
    bus = SimStageBus((1,), cycle_dt=0.02)
    bus.single_turn_feedback = True
    s = RotaryStages(lambda: bus, control_mode="position")
    s.connect()
    s.motors[0].speed_limit = 3000
    s.move_to_angle(1, 360)
    wait_for(lambda: s.fault is not None, timeout=30, what="fault")
    assert "jumped" in s.fault and bus.released == {1}
    s.disconnect()


def test_position_mode_jammed_stage_times_out(pstages):
    s, bus = pstages
    bus.jammed.add(1)
    with pytest.raises(StageTimeout):
        s.move_to_angle(1, 90, wait_for_position=True, timeout=0.5)


def test_recorder_sees_every_cycle():
    rows = []
    s, bus = make_stages(control_mode="position", recorder=lambda *row: rows.append(row))
    s.move_to_angle(1, 10, wait_for_position=True, timeout=30)
    target = s.motors[0].ticks(10)
    s.disconnect()
    assert len(rows) > 5 and rows[-1][1:4] == (1, target, target)


def test_position_mode_setup_order_on_the_real_bus():
    """ScservoBus: torque off, EEPROM (mode 0, limits 0, full-angle feedback), goal := present, then torque on."""
    from machine_core.stages import ScservoBus

    class Driver:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def call(*a):
                self.calls.append((name,) + a)
                return {"read1ByteTxRx": (0x02, 0, 0), "ReadPos": (5000, 0, 0)}.get(name, (0, 0))
            return call

        def scs_toscs(self, value, bit):
            return value

    bus = ScservoBus.__new__(ScservoBus)
    bus._ok, bus.driver = 0, Driver()
    bus.setup_position_mode(1)
    calls = [c for c in bus.driver.calls if c[0] != "read1ByteTxRx"]
    assert calls == [("EnableTorque", 1, 0), ("unLockEprom", 1), ("write1ByteTxRx", 1, 33, 0),
                     ("write2ByteTxRx", 1, 9, 0), ("write2ByteTxRx", 1, 11, 0), ("write1ByteTxRx", 1, 18, 0x12),
                     ("LockEprom", 1), ("ReadPos", 1), ("WritePosEx", 1, 5000, 0, 0), ("EnableTorque", 1, 1)]


@pytest.mark.parametrize("angle", [360, -45.1, 0.03, 0.06])
def test_position_mode_corrects_the_servo_dead_band(angle):
    """C16 measurement: the ST3215 stops 2-4 ticks short and ignores goals 1-3 ticks away; the PC aims past."""
    bus = SimStageBus((1,), cycle_dt=0.02)
    bus.servo_deadband = 3
    s = RotaryStages(lambda: bus, control_mode="position")
    s.connect()
    s.motors[0].speed_limit = 3000
    assert s.move_to_angle(1, angle, wait_for_position=True, timeout=30) is True
    assert abs(bus.motors[1]["pos"] - s.motors[0].ticks(angle)) <= 1
    s.disconnect()


def test_position_mode_without_correction_success_still_reaches_within_accept():
    bus = SimStageBus((1,), cycle_dt=0.02)
    s = RotaryStages(lambda: bus, control_mode="position")
    s.connect()
    s.motors[0].max_aim = 0                                                  # corrections cannot help
    bus.servo_deadband = 3
    logs = []
    s.on_log = lambda text, level="info": logs.append(text)
    assert s.move_to_angle(1, 10, wait_for_position=True, timeout=30) is True
    assert 1 < abs(bus.motors[1]["pos"] - s.motors[0].ticks(10)) <= 4 and "ticks from the target" in logs[-1]
    s.disconnect()
