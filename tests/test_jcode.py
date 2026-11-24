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


# --------------------------------------------------------------------------- v0.1 header (P3.2)

import hashlib  # noqa: E402

from machine_core.jcode import check_header, read_job  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def header_job(tmp_path, extra="", body=None, files=("seg 1.nc",)):
    """A v0.1 job folder: segments next to the J-code, one sha256 line per segment."""
    for name in files:
        write(tmp_path, name, GCODE)
    lines = ["; made by hand", "JH jcode=0.1", "JH creator=BildHatcher 3.0.0", "JH created=2026-11-24T10:00:00",
             "JH units=mm", "JH machine=snapmaker_artisan", "JH toolhead=laser455"]
    lines += [f"JH sha256={sha(tmp_path / name)} {name}" for name in files]
    lines += extra.splitlines()
    lines += (body or "J0 X1 Y2 Z0 R0\nJ1 seg 1.nc").splitlines()
    return write(tmp_path, "job.jcode", "\n".join(lines) + "\n")


def test_header_is_read_and_checked(tmp_path):
    job = read_job(header_job(tmp_path))
    assert job.header["jcode"] == "0.1" and job.header["toolhead"] == "laser455" and job.warnings == []
    assert list(job.header["sha256"]) == ["seg 1.nc"] and job.segments[0].ref == (1.0, 2.0, 0.0, 0.0)
    assert check_header(job.header, "snapmaker_artisan", "laser455") == []
    assert check_header(job.header, "snapmaker_artisan", "laser1064") == [
        "made for toolhead 'laser455', detected 'laser1064'"]
    assert "made for machine" in check_header(job.header, "galvo", "laser455")[0]


def test_v0_without_header_still_runs(tmp_path):
    write(tmp_path, "a.nc", GCODE)
    job = read_job(write(tmp_path, "job.jcode", f"J0 X0 Y0 Z0 R0\nJ1 {tmp_path / 'a.nc'}\n"))
    assert job.header == {} and check_header(job.header, "snapmaker_artisan", None) == []


def test_sub_folder_backslashes_and_case_match_the_sha256_line(tmp_path):
    (tmp_path / "segments").mkdir()
    write(tmp_path / "segments", "A.nc", GCODE)
    job = write(tmp_path, "job.jcode", f"JH jcode=0.1\nJH sha256={sha(tmp_path / 'segments' / 'A.nc')} segments/A.nc\n"
                                       "J0 X0 Y0 Z0 R0\n" r"J1 .\segments\a.nc" "\n")
    assert len(read_job(job).segments) == 1


@pytest.mark.parametrize("extra, body, message", [
    ("JH jcode=1.0", None, "given twice"),
    ("", "J0 X0 Y0 Z0 R0\nJH units=mm\nJ1 seg 1.nc", "must come before"),
    ("JH comment", None, "must be 'JH key=value'"),
    ("JH sha256=abc seg 1.nc", None, "64 hex digits"),
    ("", "J0 X0 Y0 Z0 R0\nJ1 {abs}", "absolute path"),
    ("", "J0 X0 Y0 Z0 R0\nJ1 ../outside.nc", "outside the job folder"),
    ("", "J0 X0 Y0 Z0 R0\nJ1 seg 1.nc\nJ1 other.nc", "no sha256 in the header for 'other.nc'"),
    ("JH sha256=" + "0" * 64 + " unused.nc", None, "files the job does not use: unused.nc"),
])
def test_header_problems_are_refused(tmp_path, extra, body, message):
    write(tmp_path.parent, "outside.nc", GCODE)
    write(tmp_path, "other.nc", GCODE)
    body = body and body.format(abs=tmp_path / "seg 1.nc")
    with pytest.raises(JobError, match=message):
        read_job(header_job(tmp_path, extra, body))


def test_changed_segment_is_refused(tmp_path):
    job = header_job(tmp_path)
    write(tmp_path, "seg 1.nc", GCODE.replace("S51", "S255"))         # edited after the job was made
    with pytest.raises(JobError, match="changed after the job was made"):
        read_job(job)


def test_header_version_and_unknown_keys(tmp_path):
    job = write(tmp_path, "job.jcode", "JH jcode=1.0\nJ0 X0\n")
    with pytest.raises(JobError, match="version 1.0 is not supported"):
        read_job(job)
    job = write(tmp_path, "job.jcode", "JH jcode=0.1\nJH units=inch\nJ0 X0\n")
    with pytest.raises(JobError, match="units 'inch' are not supported"):
        read_job(job)
    job = write(tmp_path, "job.jcode", "JH creator=x\nJ0 X0\n")
    with pytest.raises(JobError, match="header without 'JH jcode"):
        read_job(job)
    write(tmp_path, "a.nc", GCODE)
    job = write(tmp_path, "job.jcode", "JH jcode=0.2\nJH colour=blue\nJ1 a.nc\n")
    assert read_job(job).warnings == ["job.jcode:2: unknown header key 'colour' (ignored)"]
