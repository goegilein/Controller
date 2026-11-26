"""P2.8c: the real UI modules on the virtual machine – wiring as in main_Controller (without cameras / OpenGL plot)."""
import time

import pytest
from PyQt6 import QtWidgets, uic

import Artisan_GUI_Interface
import Maschine_Helper
import Process_GUI_Interface
import RotMotor_GUI_Interface
from PathManager import get_gui_file_path
from Settings_Manager import SettingsManager
from conftest import FIXTURES
from job_bridge import CoreProcessHandler
from machine_bridge import ArtisanFacade, MachineBridge, RotaryFacade, config_from_settings
from machine_core.sim import SimArtisan
from machine_core.transport import SimTransport
from machine_safety_ui import MachineBar
from test_bridge import pump, qapp  # noqa: F401  (fixture)
from test_core_job import JOBS


class App:
    def __init__(self, confirm=lambda *a: True):
        self.sim = SimArtisan(realtime=True, speedup=20)
        settings = SettingsManager(default_settings_path=FIXTURES / "settings.json")
        self.gui = uic.loadUi(str(get_gui_file_path("Controller.ui")))
        self.rot = RotaryFacade(settings=settings)
        self.rot.port = "simulator"
        self.bridge = MachineBridge(config=config_from_settings(settings), rotary=self.rot,
                                    transport_factory=lambda port, baud: SimTransport(self.sim))
        self.ac = ArtisanFacade(self.bridge, settings=settings, ask_home=lambda: True)
        self.ac.port = "simulator"
        self.ph = CoreProcessHandler(self.gui, self.ac, self.rot)
        self.artisan_ui = Artisan_GUI_Interface.ArtisanInterface(self.gui, self.ac)
        self.rot_ui = RotMotor_GUI_Interface.RotMotorInterface(self.gui, self.rot)
        self.process_ui = Process_GUI_Interface.ProcessInterface(self.gui, self.ph)
        self.helper = Maschine_Helper.MaschineHelpers(self.gui, self.ac)
        self.helper.setup_helpers()
        self.confirmed = []
        self.bar = MachineBar(self.gui, self.ac, confirm_fn=lambda *a: self.confirmed.append(a[1]) or confirm(*a))

    def sent(self):
        return [line for _, line in self.sim.trace]

    def idle(self, timeout=20):
        w = self.bridge.worker
        pump(lambda: w.state.state.value == "idle" and w._queue.empty(), timeout, "idle")

    def close(self):
        self.bridge.shutdown()
        self.rot.disconnect()
        self.sim.close()
        self.gui.close()


@pytest.fixture
def app(qapp):
    a = App()
    a.ac.connect()
    a.rot.connect()
    pump(lambda: a.bridge.worker.homed_all, what="homed")
    a.idle()
    yield a
    a.close()


def test_buttons_drive_the_virtual_machine(app):
    g = app.gui
    pump(lambda: "Idle" in app.bar.state_label.text(), timeout=15, what="idle shown")   # via the Qt event queue
    assert app.bar.stop_button.isEnabled()
    assert g.rot_mot_tabWidget.count() == 2                                 # stages found on the simulated bus
    g.axis_step_mode_button.click()
    g.axis_step_size_box.setValue(5)
    g.plus_x_button.pressed.emit()
    g.plus_x_button.released.emit()
    g.move_by_x_box.setValue(100)
    g.move_by_y_box.setValue(80)
    g.move_by_z_box.setValue(10)
    g.move_abs_button.click()
    app.idle()
    pump(lambda: g.abs_x_box.value() == 100 and g.abs_y_box.value() == 80, timeout=15, what="position in the UI")
    g.set_wp_button.click()
    g.home_axis_button.click()                                              # clicked(False) -> "G28"
    app.idle()
    sent = app.sent()
    assert "G28" in sent[3:] and not any(line.startswith("G92") for line in sent)
    assert any(line.startswith("G0 X5 ") for line in sent)


def test_process_from_the_ui_and_stop_with_confirmation(app, tmp_path):
    g = app.gui
    path = tmp_path / "long.nc"
    path.write_text("\n".join(["G90", "M4 P0"] + [f"G1 X{2 * (i + 1)} P20 S51 F600" for i in range(100)] + ["M5"]))
    app.ac.move_axis_absolute(100, 100, 0)
    app.idle()
    pump(lambda: app.ac.get_absolute_position() == [100.0, 100.0, 0.0], what="position")
    g.add_process_step_button.click()
    step = app.ph.process_step_list[0]
    app.ph.set_step_nc_file(step, str(path))
    assert step.nc_file and step.work_position[:3] == [100.0, 100.0, 0.0]
    app.sim.speedup = 2
    g.toggle_process_button.click()
    pump(lambda: "Running" in app.bar.state_label.text(), what="running")
    assert not g.plus_x_button.isEnabled()                                  # jog buttons off while running
    app.bar.request_stop()
    pump(lambda: "Idle" in app.bar.state_label.text(), timeout=10, what="idle after stop")
    assert app.confirmed == ["Stop"] and not app.sim.laser_armed and "M410" in app.sent()
    assert g.plus_x_button.isEnabled()


def test_stops_need_confirmation(qapp):
    a = App(confirm=lambda *args: False)
    a.ac.connect()
    pump(lambda: a.bridge.worker.homed_all, what="homed")
    a.idle()
    a.bar.request_stop()
    a.bar.request_estop()
    time.sleep(0.2)
    assert a.confirmed == ["Stop", "Emergency stop"]
    assert "M410" not in a.sent() and "M112" not in a.sent()
    a.close()


def test_emergency_stop_from_the_bar(app):
    app.bar.request_estop()
    pump(lambda: "E-STOP" in app.bar.state_label.text(), timeout=15, what="estop shown")
    assert app.sim.halted and not app.bar.stop_button.isEnabled()


def test_each_rotary_tab_shows_its_own_motor(app):
    """B26: v1.0 showed every motor's position in the last tab."""
    tabs = app.gui.rot_mot_tabWidget
    spin = [tabs.widget(i).findChild(QtWidgets.QDoubleSpinBox, "current_pos_spinbox") for i in range(2)]
    assert app.rot.move_to_angle(2, 30, wait_for_position=True, timeout=30)
    pump(lambda: abs(spin[1].value() - 30) < 0.5, what="tab 2 shows motor 2")
    assert abs(spin[0].value()) < 0.5


def test_main_builds_the_whole_app_without_running_it(qapp, monkeypatch):
    """P4.3: main_Controller.build() wires everything (no module-level code); shutdown stops the core.
    The G-code plotter (OpenGL, unchanged v1.0) needs a GL context the test process cannot give it – stubbed."""
    import Gcode_Plotter
    import main_Controller
    monkeypatch.setattr(Gcode_Plotter, "GCodePlotter", lambda gui, handler: None)
    a = main_Controller.build(["main_Controller.py"], show_messages=False)
    try:
        assert a.gui.windowTitle().startswith("Artisan Controller ")
        assert a.process_ui.stored_points is a.helper.stored_points
        assert a.machine_bar.ac is a.artisan and a.artisan.bridge is a.bridge
    finally:
        a.shutdown()
        a.gui.close()
    assert not a.bridge.worker._thread.is_alive()
