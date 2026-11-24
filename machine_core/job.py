"""Job runner (REVISION_PLAN.md P2.4, preflight P2.5): executes J-code jobs on the worker thread, in machine coordinates (C5).

    machine = T_laser · T_step · Trans(J0) · p_raw
T_step (4×4) maps a step's raw job coordinates to the machine (camera / crosshair frame) and may rotate the part;
T_laser is the toolhead's laser offset, a pure translation in machine coordinates (not rotated with the part).
Every G0 / G1 is sent as an absolute G90 move in machine coordinates; no G92 (C5). An axis is written when the
raw line wrote it or when the transform changes it (rotation), so a pure translation keeps the lines of v1.0.

Per segment: wait until the previous one is done (M400), move Z-safe to the segment origin, turn the rotary axis
(only with the head standing still), stream the segment with one line in flight, M400.
Pause (C4): stop streaming, wait until the queued moves are done, laser off (M5). Resume: restore the laser mode
line and the last power words on the next G1. Stop / emergency stop come through the worker's stop path.
At the end: laser off, back to the start position. The work position is never touched (fixes B18).
"""
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from machine_core import messages as m
from machine_core.jcode import Move, Other, read_job_file
from machine_core.state import MachineState as S


def translation(x, y, z):
    t = np.eye(4)
    t[:3, 3] = (x, y, z)
    return t


def rotation_z(deg):
    r = np.eye(4)
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    r[:2, :2] = [[c, -s], [s, c]]
    return r


def step_transform(x, y, z, rotation_deg=0.0, rotation=None):
    """Raw job coordinates -> machine: rotate the part about its origin, then place the origin at (x, y, z).
    `rotation` (3×3) replaces `rotation_deg` if given."""
    t = translation(x, y, z)
    if rotation is None:
        return t @ rotation_z(rotation_deg)
    r = np.eye(4)
    r[:3, :3] = np.asarray(rotation, dtype=float)
    return t @ r


# P2.6: a measured part rotation (e.g. the three-point fit of a sample holder) is a full 3×3 rotation. Only its
# rotation about Z goes into a job (decision 2026-11-24); the tilt is shown so the user sees an uneven holder.
def rz_deg(rotation):
    """Rotation about Z (deg) of a 3×3 rotation: the direction of the part's X axis in the machine X/Y plane."""
    r = np.asarray(rotation, dtype=float)
    return float(np.degrees(np.arctan2(r[1, 0], r[0, 0])))


def tilt_deg(rotation):
    """Angle (deg) between the part's Z axis and the machine Z axis."""
    r = np.asarray(rotation, dtype=float)
    return float(np.degrees(np.arccos(np.clip(r[2, 2], -1.0, 1.0))))


def rz_only(rotation):
    """The 3×3 rotation about Z with the same Rz – the part of a measured rotation that a job uses."""
    return rotation_z(rz_deg(rotation))[:3, :3]


@dataclass
class JobStep:
    name: str
    path: str
    transform: np.ndarray          # 4×4 raw -> machine (camera frame)
    rot_motor_id: int = None
    rot_base: float = 0.0          # angle of the step's work position; J0 R is added

    def to_dict(self):
        return {"name": self.name, "path": self.path, "transform": [float(v) for v in self.transform.ravel()],
                "rot_motor_id": self.rot_motor_id, "rot_base": self.rot_base}

    @classmethod
    def from_dict(cls, d):
        return cls(d["name"], d["path"], np.asarray(d["transform"], dtype=float).reshape(4, 4),
                   d.get("rot_motor_id"), d.get("rot_base", 0.0))


class JobCancelled(Exception):
    pass


def fmt(value):
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


class JobRunner:
    def __init__(self, worker, steps, rotary=None):
        self.w = worker
        self.steps = steps
        self.rotary = rotary
        self.loaded = []               # (step, [segments])
        self.mode_line = None          # last M3 / M4 line, restored on resume
        self.power_words = []          # last S / P words of a G1, restored on resume
        self.restore_power = False
        self.remaining = 0.0
        self._last_progress = 0.0

    # ------------------------------------------------------------------ preparation (before anything moves)
    def prepare(self):
        """Load every file and check the job; returns a list of problems (empty = OK)."""
        from machine_core.jcode import JobError
        problems = []
        w = self.w
        if not w.homed_all:
            problems.append("home all axes first")
        if w.laser_offset is None:
            problems.append("no known toolhead / laser offset")
        if not self.steps:
            problems.append("no process steps")
        for step in self.steps:
            try:
                segments = read_job_file(step.path)
            except JobError as e:
                problems.append(f"{step.name}: {e}")
                continue
            for seg in segments:
                for warning in seg.warnings:
                    w._log(f"{step.name}: {warning}", "warning")
            needs_rotary = step.rot_motor_id is not None or any(seg.ref[3] != 0 for seg in segments)
            if needs_rotary and (step.rot_motor_id is None or self.rotary is None):
                problems.append(f"{step.name}: needs a rotary motor (J0 R != 0)")
            if w.laser_offset is not None:
                problems += self._check_limits(step, segments)
            self.loaded.append((step, segments))
        self.remaining = sum(seg.duration for _, segs in self.loaded for seg in segs)
        return problems

    def _check_limits(self, step, segments):
        """P2.5: every move (and segment origin) in machine coordinates inside the work area; power / feed in range.
        Straight moves between points inside the (convex) work area stay inside it."""
        cfg = self.w.config
        laser = translation(*self.w.laser_offset)
        lows = np.full(3, np.inf)
        highs = np.full(3, -np.inf)
        problems = []

        def check_words(words, where):
            for word in words:
                letter, value = word[0].upper(), word[1:]
                try:
                    value = float(value)
                except ValueError:
                    continue
                limit = {"S": cfg.max_power_s, "P": cfg.max_power_p, "F": cfg.max_feed}.get(letter)
                if letter in "SP" and not 0 <= value <= limit:
                    problems.append(f"{step.name}: {where}: power {word} outside 0..{fmt(limit)}")
                elif letter == "F" and (value <= 0 or (limit is not None and value > limit)):
                    problems.append(f"{step.name}: {where}: feed {word} not allowed")

        for seg in segments:
            matrix = laser @ step.transform @ translation(*seg.ref[:3])
            points = [np.zeros(3)] + [np.asarray(item.target, float) for item in seg.items if isinstance(item, Move)]
            machine = (matrix @ np.column_stack([np.array(points), np.ones(len(points))]).T).T[:, :3]
            lows, highs = np.minimum(lows, machine.min(axis=0)), np.maximum(highs, machine.max(axis=0))
            for item in seg.items:
                if isinstance(item, Move):
                    check_words(item.words, Path(seg.source).name)
                elif item.text.split()[0].upper() in ("M3", "M4"):
                    check_words(item.text.split()[1:], Path(seg.source).name)
        if np.isfinite(lows).all():
            for i, axis in enumerate("XYZ"):
                low, high = cfg.work_area[i]
                if lows[i] < low - 1e-6 or highs[i] > high + 1e-6:
                    problems.append(f"{step.name}: {axis} {fmt(lows[i])}..{fmt(highs[i])} outside the work area "
                                    f"{fmt(low)}..{fmt(high)} (laser coordinates)")
        return list(dict.fromkeys(problems))  # one message per distinct problem

    # ------------------------------------------------------------------ execution (worker thread)
    def run(self):
        w = self.w
        start = tuple(w.position)
        laser = translation(*w.laser_offset)
        for si, (step, segments) in enumerate(self.loaded, 1):
            w._log(f"step {step.name}: {len(segments)} segment(s), about {sum(s.duration for s in segments):.0f} s")
            for gi, seg in enumerate(segments, 1):
                matrix = laser @ step.transform @ translation(*seg.ref[:3])
                self._sync(seg.duration)
                self._move_to(matrix @ np.array([0.0, 0.0, 0.0, 1.0]))
                if step.rot_motor_id is not None:
                    self._sync(0)
                    reached = self.rotary.move_to_angle(step.rot_motor_id, step.rot_base + seg.ref[3],
                                                        wait_for_position=True, cancel=w._stop_requested.is_set)
                    if reached is False:
                        raise JobCancelled()
                self._stream(seg, matrix, si, gi)
        self._sync(0)
        for line in w.config.laser_off:
            w._send(line)
        self._move_to(np.array([*start, 1.0]))
        self._sync(0)
        w._update_position()

    def _stream(self, seg, matrix, si, gi):
        w = self.w
        last = matrix @ np.array([0.0, 0.0, 0.0, 1.0])
        for item in seg.items:
            self._check_commands()
            if isinstance(item, Other):
                text = item.text
                if text.split()[0].upper() in ("M3", "M4"):
                    self.mode_line = text
            else:
                point = matrix @ np.array([*item.target, 1.0])
                words = list(item.words)
                if item.code == "G1":
                    power = [x for x in words if x[0].upper() in "SP"]
                    if power:
                        self.power_words = power
                    elif self.restore_power and self.power_words:
                        words = words + self.power_words
                    self.restore_power = False
                axes = [f"{a}{fmt(point[i])}" for i, a in enumerate("XYZ")
                        if a in item.axes or abs(point[i] - last[i]) > 1e-6]
                text = " ".join([item.code] + axes + words)
                last = point
                w.position = tuple(round(float(v), 4) for v in point[:3])
            w._send(text)
            self.remaining = max(0.0, self.remaining - item.duration)
            self._progress(si, gi)

    def _move_to(self, point):
        w = self.w
        x, y, z = (float(v) for v in point[:3])
        f = f"F{fmt(min(w.config.default_speed, w.config.max_z_speed) * 60)}"
        cur_z = w.position[2] if w.position else z
        xy, zz = f"G0 X{fmt(x)} Y{fmt(y)} {f}", f"G0 Z{fmt(z)} {f}"
        moves = [zz, xy] if cur_z < z else [xy, zz] if cur_z > z else [xy]
        for line in ["G90"] + moves:
            w._send(line)
        w.position = (x, y, z)

    def _sync(self, expected_s):
        """Wait until the planner is empty (M400); the timeout covers what may still be queued."""
        self.w._send("M400", timeout=self.w.config.ack_timeout + 2 * expected_s + 30)

    def _progress(self, si, gi):
        now = time.monotonic()
        if now - self._last_progress > 0.25:
            self._last_progress = now
            self.w._emit(m.JobProgress(si, gi, round(self.remaining, 1)))
            self.w._emit_position()

    # ------------------------------------------------------------------ commands while running
    def _check_commands(self):
        w = self.w
        while True:
            command = w._next_command_nowait()
            if command is None:
                return
            if isinstance(command, m.Pause):
                self._pause()
            else:
                w._log(f"{type(command).__name__} refused while a job runs", "warning")

    def _pause(self):
        w = self.w
        w.state.to(S.PAUSED, "pausing – finishing the queued moves")
        self._sync(16)
        w._send("M5")
        w._update_position()
        w._log("paused – laser off")
        while True:
            command = w._next_command(timeout=w.config.poll_interval)
            if command is None:
                w._update_position()
            elif isinstance(command, m.Resume):
                break
            else:
                w._log(f"{type(command).__name__} refused while paused (resume or stop)", "warning")
        if self.mode_line:
            w._send(self.mode_line)
        self.restore_power = True
        w.state.to(S.RUNNING, "resumed")
