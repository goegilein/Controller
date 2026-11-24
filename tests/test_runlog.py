"""P3.4: one run log file per job (start time stamp), with result, machine, head, files and checksums."""
import hashlib
import json

from machine_core import messages as m
from machine_core.job import JobStep, step_transform
from test_core_job import JOBS, long_job, start_job
from test_core_worker import Rig, wait_for


def logs(folder):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]


def test_finished_job_is_logged_with_files_and_checksums(tmp_path):
    runs = tmp_path / "runs"
    rig = Rig(realtime=False, run_log_dir=str(runs), app_version="2.0.0")
    rig.connect()
    start_job(rig, [JobStep("Plate A", str(JOBS / "long_moves.nc"), step_transform(100, 100, 0))])
    rig.close()
    (path,) = runs.glob("*.json")
    assert path.name.endswith("_Plate_A.json") and path.name[:4].isdigit()        # start time stamp first
    log = logs(runs)[0]
    assert log["result"] == "done" and log["ended"] and log["app_version"] == "2.0.0"
    assert log["machine"] == "snapmaker_artisan" and log["toolhead"] == "laser1064"
    assert log["laser_offset"] == [21.3, -11.3, 0.0]
    step = log["steps"][0]
    digest = hashlib.sha256((JOBS / "long_moves.nc").read_bytes()).hexdigest()
    assert step["file_sha256"] == digest and step["segments"][0]["sha256"] == digest
    assert step["transform"][0][3] == 100 and step["header"] == {}


def test_refused_job_is_logged_with_its_problems(tmp_path):
    runs = tmp_path / "runs"
    rig = Rig(realtime=False, run_log_dir=str(runs))
    rig.connect(home=False)
    start_job(rig, [JobStep("s", str(JOBS / "long_moves.nc"), step_transform(0, 0, 0))])
    start_job(rig, [JobStep("s", str(JOBS / "long_moves.nc"), step_transform(0, 0, 0))])
    rig.close()
    first, second = logs(runs)                                                        # same second: _2 suffix
    assert first["result"] == "refused" and "home all axes first" in first["message"]
    assert first["problems"][0] == "home all axes first" and second["result"] == "refused"


def test_stop_emergency_stop_and_pause_are_logged(tmp_path):
    runs = tmp_path / "runs"
    for command, result in ((m.Stop(), "stopped"), (m.EmergencyStop(), "emergency stop")):
        rig = Rig(speedup=4, run_log_dir=str(runs))
        rig.connect()
        rig.worker.submit(long_job(tmp_path))
        wait_for(lambda: rig.state == "running" and len(rig.sim.moves) > 5, what="burning")
        rig.worker.submit(m.Pause())
        wait_for(lambda: rig.state == "paused", timeout=10, what="paused")
        rig.worker.submit(m.Resume())
        wait_for(lambda: rig.state == "running", what="resumed")
        rig.worker.submit(command)
        wait_for(lambda: rig.state in ("idle", "estop") and rig.worker._queue.empty(), timeout=10, what="ended")
        wait_for(lambda: all(x["result"] != "running" for x in logs(runs)), timeout=20, what="run log finished")
        rig.close()
        assert any(x["result"] == result for x in logs(runs)), [x["result"] for x in logs(runs)]
        log = next(x for x in logs(runs) if x["result"] == result)
        assert [e["event"] for e in log["events"]] == ["paused", "resumed"] and log["duration_s"] >= 0


def test_a_header_is_logged(tmp_path):
    seg = tmp_path / "seg.nc"
    seg.write_bytes((JOBS / "long_moves.nc").read_bytes())
    jcode = tmp_path / "job.jcode"
    jcode.write_text("JH jcode=0.1\nJH creator=BildHatcher 3.0.0\nJ0 X0 Y0 Z0 R0\nJ1 seg.nc\n", encoding="utf-8")
    runs = tmp_path / "runs"
    rig = Rig(realtime=False, run_log_dir=str(runs))
    rig.connect()
    start_job(rig, [JobStep("s", str(jcode), step_transform(100, 100, 0))])
    rig.close()
    log = logs(runs)[0]
    assert log["steps"][0]["header"] == {"jcode": "0.1", "creator": "BildHatcher 3.0.0"}
    assert log["steps"][0]["segments"][0]["file"] == str(seg)


def test_no_folder_no_log_and_an_unwritable_folder_does_not_stop_the_job(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    rig = Rig(realtime=False, run_log_dir=str(blocker / "runs"))                    # cannot create a folder in a file
    rig.connect()
    start_job(rig, [JobStep("s", str(JOBS / "long_moves.nc"), step_transform(100, 100, 0))])
    assert any("run log not written" in e.text for e in rig.of(m.LogLine))
    assert any(line.startswith("G1") for line in rig.sent()) and rig.state == "idle"
    rig.close()
