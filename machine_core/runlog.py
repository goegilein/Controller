"""Run log (REVISION_PLAN.md P3.4): one JSON file per job, so every burn can be traced back.

Decision 2026-11-24 (6): a file per job in a default output folder (`Documents\\MachineControl\\runs`), named by
the start time stamp. The file is written when the job starts (result "running") and rewritten when it ends, so a
crash of the app still leaves the start behind. Refused jobs are logged too (result "refused" with the problems).

Contents: start / end time, result (done / stopped / emergency stop / error / refused) and message, app version,
machine id, toolhead and laser offset, rotary control mode, pauses, and per process step the job file with its
SHA-256, the 4×4 transform, the rotary motor and base angle, the J-code v0.1 header and every segment (file, SHA-256,
J0 reference). Writing the log never stops or fails a job: a write error is only logged as a warning.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from machine_core.jcode import sha256_of

FORMAT = "machinecontrol-runlog/1"


def _now():
    return datetime.now().astimezone()


def _sha(path):
    try:
        return sha256_of(path)
    except OSError:
        return None


class RunLog:
    def __init__(self, folder, worker, runner, problems=()):
        self.w = worker
        self.runner = runner
        self.started = _now()
        stem = self.started.strftime("%Y-%m-%d_%H%M%S")
        name = runner.steps[0].name if runner.steps else "job"
        stem += "_" + (re.sub(r"[^\w.-]+", "_", name).strip("_")[:40] or "job")
        self.folder = Path(folder)
        self.path = self.folder / f"{stem}.json"
        n = 2
        while self.path.exists():
            self.path = self.folder / f"{stem}_{n}.json"
            n += 1
        loaded = {step.name: segments for step, segments in runner.loaded}
        cfg = worker.config
        self.data = {
            "format": FORMAT,
            "started": self.started.isoformat(timespec="seconds"),
            "ended": None,
            "result": "running",
            "message": "",
            "app_version": cfg.app_version,
            "machine": cfg.machine_id,
            "toolhead": worker.toolhead,
            "laser_offset": None if worker.laser_offset is None else [float(v) for v in worker.laser_offset],
            "rotary_control_mode": getattr(runner.rotary, "control_mode", None),
            "estimated_s": round(runner.remaining, 1),
            "problems": list(problems),
            "events": [],
            "steps": [{
                "name": step.name,
                "file": str(step.path),
                "file_sha256": _sha(step.path),
                "transform": [[round(float(v), 6) for v in row] for row in step.transform],
                "rot_motor_id": step.rot_motor_id,
                "rot_base": step.rot_base,
                "header": runner.headers.get(step.name, {}),
                "segments": [{"file": seg.source, "sha256": _sha(seg.source), "ref": list(seg.ref)}
                             for seg in loaded.get(step.name, [])],
            } for step in runner.steps],
        }
        self._write()

    def finish(self, result, message=""):
        ended = _now()
        self.data.update(ended=ended.isoformat(timespec="seconds"), result=result, message=message,
                         duration_s=round((ended - self.started).total_seconds(), 1),
                         events=[{"time": t.isoformat(timespec="seconds"), "event": e}
                                 for t, e in getattr(self.runner, "events", [])])
        self._write()

    def _write(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            self.w._log(f"run log not written ({self.path}): {e}", "warning")
