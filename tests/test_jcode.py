"""P3.1: J-code v0 as specified in docs/JCODE_SPEC.md."""
import pytest

from machine_core.jcode import JobError, read_job_file

GCODE = "G90\nG21\nM4 P0\nG0 X0 Y0 F6000\nG1 X5 P20 S51 F600 (burn)\nM5\n"


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_bildhatcher_layout(tmp_path):
    """What BildHatcher's save_jcode writes today: comments, J0 with all four axes, J1 with an absolute path."""
    seg = write(tmp_path, "job_block-1_cluster-1.nc", GCODE)
    job = write(tmp_path, "job.jcode", f"; This file was created by BildHatcher\n; Created: 2026-11-24 10:00:00\n\n"
                                       f"J0 X1.5 Y-2 Z0.25 R90\nJ1 {seg}\nJ0 X0 Y0 Z0 R0\nJ1 {seg}")
    segments = read_job_file(job)
    assert [s.ref for s in segments] == [(1.5, -2.0, 0.25, 90.0), (0.0, 0.0, 0.0, 0.0)]
    assert segments[0].items[-1].text == "M5"


def test_parentheses_are_allowed_in_file_names(tmp_path):
    folder = tmp_path / "jobs (copy)"
    folder.mkdir()
    write(folder, "part (1).nc", GCODE)
    job = write(folder, "job.jcode", "J0 X0 Y0 Z0 R0\nJ1 part (1).nc ; relative to the J-code\n")
    assert len(read_job_file(job)) == 1


@pytest.mark.parametrize("line, message", [
    ("J0 X1,5 Y0", "bad number"),
    ("J0 X1 Q4", "unknown J0 word"),
    ("J2 something", "unknown J-code line"),
])
def test_bad_lines_are_refused(tmp_path, line, message):
    write(tmp_path, "a.nc", GCODE)
    job = write(tmp_path, "job.jcode", f"{line}\nJ1 a.nc\n")
    with pytest.raises(JobError, match=message):
        read_job_file(job)


def test_inch_units_are_refused(tmp_path):
    write(tmp_path, "a.nc", "G20\nG1 X1 F100\n")
    job = write(tmp_path, "job.jcode", "J0 X0 Y0 Z0 R0\nJ1 a.nc\n")
    with pytest.raises(JobError, match="G20 is not supported"):
        read_job_file(job)
