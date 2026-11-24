"""P2.8b: the process steps of the UI run as jobs on the machine core."""
import copy
import json

import numpy as np

from job_bridge import CoreProcessHandler
from machine_bridge import ArtisanFacade, MachineBridge
from machine_core.sim import SimArtisan
from machine_core.transport import SimTransport
from test_bridge import pump, qapp  # noqa: F401  (fixture)
from test_core_job import JOBS, Rotary, burns, steps_for, write_jcode, start_job
from test_core_worker import Rig


class Setup:
    def __init__(self, speedup=20, realtime=True):
        self.sim = SimArtisan(realtime=realtime, speedup=speedup)
        self.rotary = Rotary(self.sim)
        self.bridge = MachineBridge(transport_factory=lambda port, baud: SimTransport(self.sim), rotary=self.rotary)
        self.ac = ArtisanFacade(self.bridge, ask_home=lambda: True)
        self.ac.port = "simulator"
        self.ph = CoreProcessHandler(None, self.ac, None)
        self.states, self.times, self.logs = [], [], []
        self.ph.set_process_state_callback(self.states.append)
        self.ph.set_remaining_time_callback(self.times.append)
        self.ph.set_log_callback(self.logs.append)
        self.ac.connect()
        pump(lambda: self.bridge.worker.homed_all, what="homed")
        self.settle()

    def settle(self, timeout=20):
        w = self.bridge.worker
        pump(lambda: w.state.state.value == "idle" and w._queue.empty(), timeout, "idle")

    def add_step(self, wp, path, motor=None):
        self.ac.move_axis_absolute(*wp[:3])
        self.settle()
        pump(lambda: self.ac.get_absolute_position() == [float(v) for v in wp[:3]], what="position")
        step = self.ph.add_process_step(name=f"Step {len(self.ph.process_step_list) + 1}")
        step.rot_motor_id = motor
        if motor is not None:
            step.work_position[3] = wp[3]
        self.ph.set_step_nc_file(step, str(path))
        assert step.nc_file, self.ph.last_log
        return step

    def close(self):
        self.bridge.shutdown()
        self.sim.close()


def test_job_from_the_process_steps_burns_like_the_runner(qapp, tmp_path):
    jcode = write_jcode(tmp_path)
    s = Setup(realtime=False)
    s.add_step([150, 150, 20, 10], jcode, motor=1)
    s.add_step([50, 60, 0], JOBS / "long_moves.nc")
    start = len(s.sim.moves)
    s.ph.start_process()
    pump(lambda: s.states[-2:] == ["Running", "Idle"], timeout=60, what="job done")
    got = [(pos, armed) for code, pos, armed in s.sim.moves[start:] if code == "G1"]
    s.close()

    rig = Rig(realtime=False, rotary=Rotary(None))
    rig.worker.rotary.sim = rig.sim
    rig.connect()
    start_job(rig, steps_for(jcode))
    expected = burns(rig.sim)
    rig.close()
    assert len(got) == len(expected) > 40
    assert all(np.allclose(a[0], b[0], atol=1e-6) and a[1] == b[1] for a, b in zip(got, expected))
    assert s.times[-1] == "ETA. - 0:0:0"


def test_pause_resume_cancel(qapp, tmp_path):
    s = Setup(speedup=2)
    path = tmp_path / "long.nc"
    path.write_text("\n".join(["G90", "M4 P0"] + [f"G1 X{2 * (i + 1)} P20 S51 F600" for i in range(100)] + ["M5"]))
    s.add_step([100, 100, 0], path)
    s.ph.start_process()
    pump(lambda: s.ph.process_state == "Running", what="running")
    s.ph.pause_process()
    pump(lambda: s.ph.process_state == "Paused", timeout=10, what="paused")
    pump(lambda: s.sim.laser_mode is None, timeout=10, what="laser off")
    s.ph.resume_process()
    pump(lambda: s.ph.process_state == "Running", what="resumed")
    s.ph.cancel_process()
    s.settle()
    sent = [line for _, line in s.sim.trace]
    after = sent[sent.index("M410"):]
    assert not any(line.startswith(("G0", "G1")) for line in after)       # no return move (agreed change)
    pump(lambda: s.states[-1] == "Idle", what="Idle in the UI")                # state events arrive via the Qt queue
    assert not s.sim.laser_armed
    s.close()


def test_bounding_box_twice_is_the_same_and_leaves_the_box_alone(qapp):
    """B10: v1.0 added the laser offset to the stored box on every run and left a G92 behind."""
    s = Setup(realtime=False)
    step = s.add_step([100, 120, 5], JOBS / "long_moves.nc")
    box = copy.deepcopy(step.bounding_box)
    runs = []
    for _ in range(2):
        start = len(s.sim.trace)
        s.ph.run_bounding_box(0, in_laser_coord=True)
        s.settle()
        runs.append([line for _, line in s.sim.trace[start:] if line.startswith("G0")])
    assert runs[0] == runs[1] and step.bounding_box == box
    corners = s.ph.bounding_box_corners(0, in_laser_coord=True)
    (x0, _), (_, y1), (_, z1) = box[:3]
    assert np.allclose(corners[0], (100 + 21.3 + x0, 120 - 11.3 + y1, 5 + z1))
    assert not any(line.startswith("G92") for _, line in s.sim.trace)
    assert s.ac.work_position == (0.0, 0.0, 0.0)
    pump(lambda: s.ac.get_absolute_position() == [100.0, 120.0, 5.0], what="back at the work position")
    s.close()
