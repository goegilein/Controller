"""P2.6: part rotation per process step – from the three-point holder fit via a stored position into the job."""
import json

import numpy as np
import pytest

import Maschine_Helper
from job_bridge import CoreProcessHandler
from machine_core.job import rotation_z, rz_deg, rz_only, tilt_deg
from test_app_smoke import App
from test_bridge import pump, qapp  # noqa: F401  (fixture)
from test_core_job import JOBS
from test_job_bridge import Setup


def tilted(rz, tilt_x):
    """Rotation about Z by rz, then a tilt about X (an uneven holder)."""
    c, s = np.cos(np.radians(tilt_x)), np.sin(np.radians(tilt_x))
    rx = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    return rotation_z(rz)[:3, :3] @ rx


def test_rz_tilt_and_rz_only():
    r = tilted(30, 2)
    assert rz_deg(r) == pytest.approx(30) and tilt_deg(r) == pytest.approx(2)
    assert np.allclose(rz_only(r), rotation_z(30)[:3, :3])
    assert tilt_deg(rz_only(r)) == pytest.approx(0, abs=1e-9)


def test_stored_positions_keep_the_rotation(tmp_path):
    path = tmp_path / "stored.json"
    path.write_text(json.dumps([{"name": "old", "x": 1, "y": 2, "z": 3}]), encoding="utf-8")  # v1.0 file
    points = Maschine_Helper.StoredPoints(file_path=path)
    assert points.get_by_name("old").rotation is None
    points.add_point(10, 20, 5, name="holder", rotation=tilted(15, 1))
    again = Maschine_Helper.StoredPoints(file_path=path)
    assert np.allclose(again.get_by_name("holder").rotation, tilted(15, 1))
    assert json.loads(path.read_text(encoding="utf-8"))[0] == {"name": "old", "x": 1.0, "y": 2.0, "z": 3.0}


def test_holder_fit_stores_its_rotation(tmp_path, monkeypatch):
    """The three-point fit measured a rotated holder: storing its centre keeps the rotation (v1.0 dropped it)."""
    points = Maschine_Helper.StoredPoints(file_path=tmp_path / "stored.json")
    holders = Maschine_Helper.CustomSampleHolders(None, None, stored_points=points, file_path=tmp_path / "none.json")
    local = {"Point1": (0, 0, 0), "Point2": (50, 0, 0), "Point3": (0, 30, 0)}
    holders.holders_data = {"H": {k: {"X": v[0], "Y": v[1], "Z": v[2]} for k, v in local.items()}}
    holders.current_holder_name = "H"
    r, t = rotation_z(20)[:3, :3], np.array([100.0, 120.0, 4.0])
    holders.measured_points = {k: r @ np.array(v, float) + t for k, v in local.items()}
    holders.calculate_transformation()
    monkeypatch.setattr(Maschine_Helper.QInputDialog, "getText", lambda *a, **k: ("H centre", True))
    holders.store_center_position()
    stored = points.get_by_name("H centre")
    assert np.allclose([stored.X, stored.Y, stored.Z], t) and rz_deg(stored.rotation) == pytest.approx(20)


def test_rotated_step_burns_rotated_and_flat(qapp):
    s = Setup(realtime=False)
    step = s.add_step([100, 100, 0], JOBS / "long_moves.nc")
    point = Maschine_Helper.Point(100, 100, 0, name="holder", rotation=tilted(90, 1.5))
    assert s.ph.set_step_from_stored_point(step, point)
    start = len(s.sim.moves)
    s.ph.start_process()
    pump(lambda: s.states[-2:] == ["Running", "Idle"], timeout=60, what="job done")
    burns = [pos for code, pos, _ in s.sim.moves[start:] if code == "G1"]
    origin = np.array([100, 100, 0]) + [21.3, -11.3, 0]
    assert np.allclose(burns[0], origin + [0, 10, 0], atol=1e-6)            # raw X10 -> machine Y+10 (Rz 90°)
    assert all(abs(p[2]) < 1e-6 for p in burns[:5])                          # XY lines stay at Z0: tilt not applied
    assert np.allclose(s.ph.part_coordinates(step, origin[:3] + [0, 10, 0] - [21.3, -11.3, 0]), [10, 0, 0])
    s.close()


def test_bounding_box_rotates_with_the_part(qapp):
    s = Setup(realtime=False)
    step = s.add_step([100, 100, 0], JOBS / "long_moves.nc")
    plain = s.ph.bounding_box_corners(0)
    step.rotation = rotation_z(90)[:3, :3].tolist()
    rotated = s.ph.bounding_box_corners(0)
    for (x, y, z), (rx, ry, rz) in zip(plain, rotated):
        assert np.allclose((rx - 100, ry - 100, rz), (-(y - 100), x - 100, z), atol=1e-6)
    s.ph.reset_step_rotation(step)
    assert s.ph.bounding_box_corners(0) == plain
    s.close()


def test_rotation_button_and_dialog(qapp, tmp_path):
    app = App()
    app.ac.connect()
    pump(lambda: app.bridge.worker.homed_all, what="homed")
    app.idle()
    app.process_ui.stored_points = app.helper.stored_points
    app.helper.stored_points.add_point(150, 80, 2, name="holder", rotation=tilted(12.5, 0.8), save=False)
    app.gui.add_process_step_button.click()
    widget = app.process_ui.process_steps_listWidget.itemWidget(app.process_ui.process_steps_listWidget.item(0))
    button = widget.findChild(type(app.gui.add_process_step_button), "rotation_button")
    assert button.text() == "Rot\n0.00°"
    dialog = widget.rotation_dialog_factory()
    dialog.points.setCurrentIndex(next(i for i in range(dialog.points.count())
                                       if dialog.points.itemText(i).startswith("holder ")))
    dialog.apply_stored_point()
    assert "12.500°" in dialog.info.text() and "Tilt above" in dialog.info.text()
    step = app.ph.process_step_list[0]
    assert step.work_position[:3] == [150.0, 80.0, 2.0] and step.rotation_source == "holder"
    app.process_ui.refresh_step_widget(step, widget)
    assert widget.wp_x_spinbox.value() == 150
    dialog.reset()
    assert step.rotation is None and "Not rotated" in dialog.info.text()
    app.close()
