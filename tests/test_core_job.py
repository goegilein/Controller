"""P2.4: job runner on the simulated Artisan – same burn path as v1.0, machine coordinates, pause / stop safety."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

import Process_Handler
from conftest import FIXTURES, make_artisan
from machine_core import messages as m
from machine_core.job import JobStep, step_transform
from machine_core.sim import SimArtisan
from sim_artisan import FakeRotMotors
from test_core_worker import Rig, wait_for

JOBS = FIXTURES / "jobs"
LASER_1064 = np.array([21.3, -11.3, 0.0])


class Rotary:
    """Records rotary moves and whether the head stood still at that moment."""

    def __init__(self, sim):
        self.sim = sim
        self.calls = []

    def move_to_angle(self, sid, angle, wait_for_position=False, **kwargs):
        still = not self.sim._planner and not self.sim._busy_block
        self.calls.append((sid, angle, wait_for_position, still))


def write_jcode(tmp_path, relative=False):
    cluster = "cluster_over_drive.nc" if relative else JOBS / "cluster_over_drive.nc"
    long_moves = "long_moves.nc" if relative else JOBS / "long_moves.nc"
    folder = tmp_path if relative else tmp_path
    if relative:
        for name in ("cluster_over_drive.nc", "long_moves.nc"):
            (tmp_path / name).write_text((JOBS / name).read_text(encoding="utf-8"), encoding="utf-8")
    jcode = folder / "job.jcode"
    jcode.write_text(f"; test\nJ0 X0 Y0 Z0 R0\nJ1 {cluster}\nJ0 X40 Y-10 Z1.5 R90 ; second\nJ1 {long_moves}\n", encoding="utf-8")
    return jcode


def steps_for(jcode):
    return [JobStep("Step 1", str(jcode), step_transform(150, 150, 20), rot_motor_id=1, rot_base=10),
            JobStep("Step 2", str(JOBS / "long_moves.nc"), step_transform(50, 60, 0))]


def start_job(rig, steps, state="idle", timeout=20):
    rig.worker.submit(m.StartJob(tuple(s.to_dict() for s in steps)))
    time.sleep(0.05)
    wait_for(lambda: rig.state == state and rig.worker._queue.empty(), timeout, f"state {state}")


def burns(sim):
    return [(pos, armed) for code, pos, armed in sim.moves if code == "G1"]


# --------------------------------------------------------------------------- equivalence with v1.0

def test_same_burn_path_as_v1(monkeypatch, tmp_path):
    """C5 changes how coordinates are sent (machine coordinates instead of G92), not where the laser burns."""
    jcode = write_jcode(tmp_path)

    old_sim = SimArtisan()
    old = make_artisan(monkeypatch, old_sim)
    monkeypatch.setattr(Process_Handler, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    ph = Process_Handler.ProcessHandler(None, old, FakeRotMotors(old_sim))
    for wp, path, motor in (([150, 150, 20, 10], jcode, 1), ([50, 60, 0, 0], JOBS / "long_moves.nc", None)):
        old.move_axis_absolute(*wp[:3])
        step = ph.add_process_step(name="s")
        step.rot_motor_id = motor
        step.work_position[3] = wp[3]
        ph.set_step_nc_file(step, str(path))
    start = len(old_sim.moves)
    ph.start_process()
    if ph.execution_thread is not None:
        ph.execution_thread.join(30)
    old.connected = False
    old_burns = [(pos, armed) for code, pos, armed in old_sim.moves[start:] if code == "G1"]

    rig = Rig(realtime=False, rotary=Rotary(None))
    rig.worker.rotary.sim = rig.sim
    rig.connect()
    start_job(rig, steps_for(jcode))
    new_burns = burns(rig.sim)
    rig.close()

    assert len(new_burns) == len(old_burns) > 40
    for (p_new, armed_new), (p_old, armed_old) in zip(new_burns, old_burns):
        assert np.allclose(p_new, p_old, atol=1.5e-3), (p_new, p_old)
        assert armed_new == armed_old


# --------------------------------------------------------------------------- coordinates and loading

def test_machine_coordinates_only_and_work_position_untouched(tmp_path):
    rig = Rig(realtime=False, rotary=Rotary(None))
    rig.worker.rotary.sim = rig.sim
    rig.connect()
    rig.submit_and_wait(m.MoveTo(10, 20, 3))
    rig.submit_and_wait(m.SetWorkPosition())
    start_job(rig, steps_for(write_jcode(tmp_path, relative=True)))  # J1 paths relative to the J-code (B09)
    sent = rig.sent()
    assert not any(line.startswith(("G92", "G91")) for line in sent)
    assert rig.worker.work_position == (10.0, 20.0, 3.0)                  # B18
    assert rig.worker.position == (10.0, 20.0, 3.0)                        # back at the start
    assert sent[-3:-1] == ["M5", "M9"] or "M5" in sent[-8:]
    assert "===" not in sent                                               # B24
    assert any("not a command" in e.text for e in rig.of(m.LogLine))
    rig.close()


def test_rotary_turns_only_while_the_head_stands_still(tmp_path):
    rotary = Rotary(None)
    rig = Rig(speedup=50, rotary=rotary)
    rotary.sim = rig.sim
    rig.connect()
    start_job(rig, steps_for(write_jcode(tmp_path)), timeout=30)
    assert [(c[0], c[1]) for c in rotary.calls] == [(1, 10), (1, 100)]
    assert all(c[2] and c[3] for c in rotary.calls)
    rig.close()


def test_rotated_part():
    """A step rotated by 90°: the raw +X line burns along machine +Y."""
    rig = Rig(realtime=False)
    rig.connect()
    step = JobStep("rotated", str(JOBS / "long_moves.nc"), step_transform(100, 100, 0, rotation_deg=90))
    start_job(rig, [step])
    first_burn = burns(rig.sim)[0][0]
    origin = np.array([100, 100, 0]) + LASER_1064
    assert np.allclose(first_burn, origin + [0, 10, 0], atol=1e-6)        # raw X10 -> machine Y+10
    assert "G1 X121.3 Y98.7 P20 S51 F600" in rig.sent()                    # both axes written after rotation
    rig.close()


@pytest.mark.parametrize("content, message", [
    ("J0 X0 Y0 Z0 R0\nJ1 missing.nc\n", "not found"),
    ("J0 X0 Y0 Z0 R0\nJ1 {bad}\n", "G92 is not supported"),
    ("J0 X0 Y0 Z0 R5\nJ1 {good}\n", "needs a rotary motor"),
])
def test_bad_jobs_are_refused_before_anything_moves(tmp_path, content, message):
    (tmp_path / "bad.nc").write_text("G90\nG92 X0 Y0\nG1 X1\n", encoding="utf-8")
    jcode = tmp_path / "job.jcode"
    jcode.write_text(content.format(bad=tmp_path / "bad.nc", good=JOBS / "long_moves.nc"), encoding="utf-8")
    rig = Rig(realtime=False)
    rig.connect()
    before = len(rig.sim.trace)
    start_job(rig, [JobStep("s", str(jcode), step_transform(0, 0, 0))])
    assert any(message in e.text for e in rig.of(m.LogLine)), [e.text for e in rig.of(m.LogLine)]
    assert not any(line.startswith(("G0", "G1")) for _, line in rig.sim.trace[before:])
    rig.close()


def test_job_needs_homing():
    rig = Rig(realtime=False)
    rig.connect(home=False)
    start_job(rig, [JobStep("s", str(JOBS / "long_moves.nc"), step_transform(0, 0, 0))])
    assert any("home all axes first" in e.text for e in rig.of(m.LogLine))
    rig.close()


# --------------------------------------------------------------------------- pause / stop / errors while running

def long_job(tmp_path):
    """120 burn segments of 2 mm at 600 mm/min (0.2 s each): long enough that pause / stop hit a running stream."""
    path = tmp_path / "long_job.nc"
    lines = ["G90", "M4 P0", "G0 X0 Y0 F6000"] + [f"G1 X{2 * (i + 1)} Y{i % 2} P20 S51 F600" for i in range(120)] + ["M5"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return m.StartJob((JobStep("long", str(path), step_transform(100, 100, 0)).to_dict(),))


def slow_rig():
    rig = Rig(speedup=4)
    rig.connect()
    return rig


def test_pause_switches_the_laser_off_and_resume_restores_power(tmp_path):
    rig = slow_rig()
    rig.worker.submit(long_job(tmp_path))
    wait_for(lambda: any(armed for _, armed in burns(rig.sim)), what="burning")
    rig.worker.submit(m.Pause())
    wait_for(lambda: rig.state == "paused" and rig.sim.laser_mode is None, timeout=10, what="paused, laser off")
    emitted = len(rig.sim.standstill_emission)
    rig.submit_and_wait(m.Jog("X", 1, 10), state="paused")                 # refused: no jogging in pause
    time.sleep(0.3)
    assert len(rig.sim.standstill_emission) == emitted                     # nothing fires while paused
    assert not any(line.startswith("G0 X1 ") for line in rig.sent())
    rig.worker.submit(m.Resume())
    wait_for(lambda: rig.state == "idle", timeout=20, what="job finished")
    sent = rig.sent()
    i = sent.index("M5")
    assert sent[i + 1] == "M114" and "M4 P0" in sent[i + 1:i + 6]        # laser mode restored on resume
    resumed = sent[sent.index("M4 P0", i):]
    first_g1 = next(line for line in resumed if line.startswith("G1"))
    assert "P20 S51" in first_g1                                           # power restored on the first G1
    rig.close()


def test_stop_during_a_job(tmp_path):
    rig = slow_rig()
    rig.worker.submit(long_job(tmp_path))
    wait_for(lambda: any(armed for _, armed in burns(rig.sim)), what="burning")
    rig.worker.submit(m.Stop())
    wait_for(lambda: rig.state == "idle" and rig.worker._queue.empty(), timeout=5, what="idle after stop")
    time.sleep(0.3)
    sent = rig.sent()
    after = sent[sent.index("M410"):]
    assert after[:3] == ["M410", "M5", "M9"]
    assert not any(line.startswith(("G0", "G1")) for line in after)        # no return move: the user decides
    assert not rig.sim.laser_armed
    rig.close()


def test_emergency_stop_during_a_job(tmp_path):
    rig = slow_rig()
    rig.worker.submit(long_job(tmp_path))
    wait_for(lambda: any(armed for _, armed in burns(rig.sim)), what="burning")
    rig.worker.submit(m.EmergencyStop())
    wait_for(lambda: rig.state == "estop" and rig.sim.halted, what="estop")
    time.sleep(0.3)
    sent = rig.sent()
    assert sent[-1] == "M112" and not rig.sim.laser_armed
    rig.close()


def test_cable_pulled_during_a_job(tmp_path):
    rig = slow_rig()
    rig.worker.submit(long_job(tmp_path))
    wait_for(lambda: any(armed for _, armed in burns(rig.sim)), what="burning")
    rig.sim.fail_after = len(rig.sim.trace)
    wait_for(lambda: rig.state == "error", timeout=15, what="error")
    assert "connection lost" in rig.of(m.ErrorRaised)[0].message
    rig.submit_and_wait(m.Resume(), state="error")                         # nothing resumes
    rig.close()


# --------------------------------------------------------------------------- preflight (P2.5)

@pytest.mark.parametrize("transform, lines, message", [
    (step_transform(390, 100, 0), ["G1 X10 F600"], "X 411.3..421.3 outside the work area 0..400"),   # laser offset +21.3
    (step_transform(100, 5, 0), ["G0 Y-10 F6000"], "Y -16.3..-6.3 outside"),
    (step_transform(100, 100, 0, rotation_deg=90), ["G1 X320 F600"], "Y 88.7..408.7 outside"),        # rotated part
    (step_transform(100, 100, 0), ["M3 S300", "G1 X10 F600"], "power S300 outside 0..255"),
    (step_transform(100, 100, 0), ["M4 P0", "G1 X10 P120 F600"], "power P120 outside 0..100"),
    (step_transform(100, 100, 0), ["G1 X10 F0"], "feed F0 not allowed"),
])
def test_preflight_refuses_jobs_outside_the_limits(tmp_path, transform, lines, message):
    path = tmp_path / "job.nc"
    path.write_text("\n".join(["G90"] + lines + ["M5"]), encoding="utf-8")
    rig = Rig(realtime=False)
    rig.connect()
    before = len(rig.sim.trace)
    start_job(rig, [JobStep("s", str(path), transform)])
    errors = [e.text for e in rig.of(m.LogLine) if e.level == "error"]
    assert any(message in text for text in errors), errors
    assert not any(line.startswith(("G0", "G1", "M3", "M4")) for _, line in rig.sim.trace[before:])
    rig.close()


def test_preflight_feed_limit_when_configured(tmp_path):
    rig = Rig(realtime=False, max_feed=3000)
    rig.connect()
    start_job(rig, [JobStep("s", str(JOBS / "long_moves.nc"), step_transform(100, 100, 0))])
    assert any("not allowed" in e.text for e in rig.of(m.LogLine) if e.level == "error")
    rig.close()


def test_manual_move_outside_the_work_area_is_refused():
    rig = Rig(realtime=False)
    rig.connect()
    rig.submit_and_wait(m.MoveTo(401, 10, 0))
    assert not any(line.startswith("G0 X401") for line in rig.sent())
    assert any("outside the work area" in e.text for e in rig.of(m.LogLine))
    rig.close()
