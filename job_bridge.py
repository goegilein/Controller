"""Process steps on the machine core (REVISION_PLAN.md P2.8b).

`CoreProcessHandler` keeps the step management of the v1.0 `ProcessHandler` (add / remove / reorder steps, work
positions, files – the UI is unchanged) and runs jobs, pause / resume / cancel and the bounding box through the
machine worker. The v1.0 class stays untouched as the reference for the characterization tests.

A step's work position [x, y, z, r] is in machine coordinates (camera / crosshair frame), as before; it becomes the
step transform `step_transform(x, y, z)` and the rotary base angle r (C5).
"""
from Process_Handler import ProcessHandler
from machine_core import messages as m
from machine_core.job import JobStep, step_transform


class CoreProcessHandler(ProcessHandler):
    def __init__(self, gui, artisan_facade, rot_motor_controller):
        super().__init__(gui, artisan_facade, rot_motor_controller)
        artisan_facade.set_process_state_callback(self._on_machine_process_state)
        artisan_facade.progress_callbacks.append(lambda e: setattr(self, "remaining_time", e.remaining_s))

    # the process state is the machine's (running / paused / anything else = Idle), not a copy kept here
    @property
    def process_state(self):
        return self.controller.process_state

    @process_state.setter
    def process_state(self, value):
        pass  # set by the machine only

    def _on_machine_process_state(self, state):
        if state == "Idle":
            self.remaining_time = 0
        for callback in self.process_state_callbacks:
            callback(state)

    # ------------------------------------------------------------------ jobs
    def job_steps(self):
        steps = []
        for step in self.process_step_list:
            x, y, z, r = (list(step.work_position) + [0.0])[:4]
            steps.append(JobStep(step.name or "step", step.nc_file, step_transform(x, y, z),
                                 rot_motor_id=step.rot_motor_id, rot_base=float(r) if step.rot_motor_id is not None else 0.0))
        return steps

    def start_process(self):
        if self.process_state != "Idle":
            self.last_log = "Execution already in progress or paused. Please cancel or resume first."
            return
        if not self.pre_start_check():
            return
        self.recalc_process_params()
        self.last_log = "Start Processing..."
        self.controller.bridge.submit(m.StartJob(tuple(s.to_dict() for s in self.job_steps())))

    def pause_process(self):
        self.controller.bridge.submit(m.Pause())
        self.last_log = "Pausing – the queued moves finish, then the laser is switched off."

    def resume_process(self):
        self.controller.bridge.submit(m.Resume())
        self.last_log = "Execution resumed."

    def cancel_process(self):
        """Software stop: quick stop and laser off; the head stays where it is (v1.0 drove back to the start)."""
        self.controller.stop()
        self.last_log = "Execution canceled."

    # ------------------------------------------------------------------ bounding box
    def bounding_box_corners(self, step_idx, in_laser_coord=False):
        """Machine coordinates of the box path: upper rectangle, lower rectangle if the box is not flat.
        The step's stored box is not changed (B10)."""
        step = self.process_step_list[step_idx]
        (x0, x1), (y0, y1), (z0, z1) = step.bounding_box[:3]
        ox, oy, oz = self.controller.laser_offset if in_laser_coord else (0.0, 0.0, 0.0)
        wx, wy, wz = step.work_position[:3]
        layers = [z1] if z0 == z1 else [z1, z0]
        corners = []
        for z in layers:
            for x, y in ((x0, y1), (x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                corners.append((wx + ox + x, wy + oy + y, wz + oz + z))
        return corners

    def run_bounding_box(self, step_idx, in_laser_coord=False):
        if self.process_state != "Idle":
            self.last_log = "Error: Cannot run the bounding box while a process is active."
            return
        if in_laser_coord and self.controller.laser_offset is None:
            self.last_log = "Error: no toolhead / laser offset known."
            return
        step = self.process_step_list[step_idx]
        wx, wy, wz = step.work_position[:3]
        speed = self.controller.speed
        submit = self.controller.bridge.submit
        submit(m.MoveTo(wx, wy, wz, speed, frame="absolute", z_safe=True))
        for x, y, z in self.bounding_box_corners(step_idx, in_laser_coord):
            submit(m.MoveTo(x, y, z, speed, frame="absolute", z_safe=False))
        submit(m.MoveTo(wx, wy, wz, speed, frame="absolute", z_safe=True))
