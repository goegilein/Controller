"""Characterization ("golden master") tests: what the current code sends to the Artisan (REVISION_PLAN.md P0.4).

They pin the behaviour of baseline 3605785 – including known bugs (B03, B10, B24, ...) – so the rework can be
checked for unintended changes. Intended changes are documented in the plan and the golden files regenerated:
    UPDATE_GOLDEN=1 python -m pytest tests/test_characterization.py

Trace lines are "<thread> <line>"; ui = MainThread, job = job thread. Lines of the background position
tracking (M114 every 0.1 s) are left out because their number depends on timing.
"""
import difflib
import json
import os
import re
from pathlib import Path

import pytest

from conftest import FIXTURES, make_artisan
from Process_Handler import NCCodeInterpreter
from sim_artisan import SimArtisan

GOLDEN_DIR = Path(__file__).parent / "golden"
JOBS = FIXTURES / "jobs"
UPDATE_GOLDEN = os.environ.get("UPDATE_GOLDEN") == "1"


def check_golden(name, text):
    path = GOLDEN_DIR / name
    if UPDATE_GOLDEN or not path.exists():
        path.write_text(text, encoding="utf-8")
        if not UPDATE_GOLDEN:
            pytest.fail(f"golden file {name} created – check it and commit it")
        return
    expected = path.read_text(encoding="utf-8")
    if text != expected:
        diff = "".join(difflib.unified_diff(expected.splitlines(True), text.splitlines(True), "golden", "now", n=2))
        pytest.fail(f"{name} differs from golden:\n{diff[:4000]}")


def role(thread_name):
    if thread_name == "MainThread":
        return "ui"
    if thread_name.endswith("(execute)"):
        return "job"
    return re.sub(r"^Thread-\d+ ", "", thread_name)


def trace_text(sim, start=0):
    lines = [f"{role(t):4} {line}" for t, line in sim.trace[start:] if not t.endswith("(track_axis)")]
    return "\n".join(lines) + "\n"


def run_job(ph):
    ph.start_process()
    thread = ph.execution_thread
    assert thread is not None, ph.last_log
    thread.join(timeout=60)
    assert not thread.is_alive(), "job did not finish"
    assert ph.process_state == "Idle"


def add_step(ph, artisan, wp, nc_file, rot_motor_id=None):
    artisan.move_axis_absolute(*wp[:3])
    step = ph.add_process_step(name=f"Step {len(ph.process_step_list) + 1}")
    step.rot_motor_id = rot_motor_id
    if rot_motor_id is not None:
        step.work_position[3] = wp[3]
    ph.set_step_nc_file(step, str(nc_file))
    assert step.nc_file, ph.last_log
    return step


# --------------------------------------------------------------------------- connection

@pytest.mark.parametrize("toolhead, offset", [("laser1064", [21.3, -11.3, 0]), ("laser455", [-21, 0, 0])])
def test_connect(monkeypatch, toolhead, offset):
    sim = SimArtisan(toolhead=toolhead)
    controller = make_artisan(monkeypatch, sim)
    try:
        assert controller.tool_head == toolhead
        assert controller.laser_offset == offset
        check_golden("connect.txt", trace_text(sim))
    finally:
        controller.connected = False


# --------------------------------------------------------------------------- manual operation

def test_manual_operations(sim, artisan):
    start = len(sim.trace)
    artisan.move_axis_step("X", 1, distance=5, speed=20)
    artisan.move_axis_step("Z", -1, distance=2, speed=50)        # Z speed limited to 30
    artisan.move_axis_absolute(120, 80, 10, speed=50)             # Z up first, all speeds limited to 30
    artisan.move_axis_absolute(100, 100, 4)                       # X/Y first, then Z down
    artisan.set_work_position()
    artisan.move_axis_to("relative", 1.5, -2, 0, speed=10)
    artisan.move_to_work_position()
    for setter in (artisan.set_laser_crosshair, artisan.set_enclosure_light, artisan.set_enclosure_fan, artisan.set_air_assist):
        setter("on")
        setter("off")
    artisan.home_axis("Z")  # resets the app's origin offset of all axes, the firmware keeps the X/Y shift (B15)
    shown = artisan.get_absolute_position()
    check_golden("manual_operations.txt", trace_text(sim, start) + f"# shown absolute position after G28 Z: {shown}, machine: {sim.machine}\n")


# --------------------------------------------------------------------------- jobs

def test_job_single_gcode(sim, artisan, process_handler):
    ph = process_handler
    add_step(ph, artisan, [100, 120, 5], JOBS / "cluster_over_drive.nc")
    start = len(sim.trace)
    run_job(ph)
    check_golden("job_single_gcode.txt", trace_text(sim, start))
    assert artisan.get_absolute_position()[:2] == [100, 120]


def test_job_jcode_with_rotary(tmp_path, sim, artisan, process_handler):
    jcode = tmp_path / "job.jcode"
    jcode.write_text(
        "; This file was created by BildHatcher\n"
        f"J0 X0 Y0 Z0 R0\nJ1 {JOBS / 'cluster_over_drive.nc'}\n"
        f"J0 X40 Y-10 Z1.5 R90 ; second cluster\nJ1 {JOBS / 'long_moves.nc'}\n",
        encoding="utf-8")
    ph = process_handler
    add_step(ph, artisan, [150, 150, 20, 10], jcode, rot_motor_id=1)
    add_step(ph, artisan, [50, 60, 0], JOBS / "long_moves.nc")
    start = len(sim.trace)
    run_job(ph)
    check_golden("job_jcode_with_rotary.txt", trace_text(sim, start))


def test_bounding_box_laser_coordinates_twice(sim, artisan, process_handler):
    """Pins B10: the laser offset is added to the stored bounding box on every run."""
    ph = process_handler
    step = add_step(ph, artisan, [100, 120, 5], JOBS / "long_moves.nc")
    box_before = json.dumps(step.bounding_box)
    start = len(sim.trace)
    ph.run_bounding_box(0, in_laser_coord=True)
    ph.run_bounding_box(0, in_laser_coord=True)
    check_golden("bounding_box_laser_twice.txt", f"box before: {box_before}\nbox after: {json.dumps(step.bounding_box)}\n" + trace_text(sim, start))


# --------------------------------------------------------------------------- file interpretation

@pytest.mark.parametrize("name", ["cluster_over_drive.nc", "long_moves.nc"])
def test_interpreter(name):
    command_lists, time_lists, box, file_type, jcode_list = NCCodeInterpreter().interpret_nc_file(str(JOBS / name))
    result = {
        "file_type": file_type,
        "jcode": jcode_list,
        "bounding_box": box,
        "total_time_s": round(sum(map(sum, time_lists)), 6),
        "commands": [[f"{t:.6f}  {c}" for c, t in zip(cmds, times)] for cmds, times in zip(command_lists, time_lists)],
    }
    check_golden(f"interpret_{Path(name).stem}.json", json.dumps(result, indent=1) + "\n")
