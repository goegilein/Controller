"""Machine Control – start of the application (REVISION_PLAN.md P4.3: `main()` instead of module-level wiring).

    python main_Controller.py [--migrate-from <folder>]

`build(argv)` creates the window, the settings, the machine core with its facades and every UI module, and returns
them (an `App` namespace) without running the event loop – the tests and tools use it. `main()` runs the app.
See README.md for the modules.
"""
import json
import sys
from types import SimpleNamespace

from PyQt6 import QtWidgets

import Artisan_GUI_Interface
import Camera_Controller
import Camera_GUI_Interface
import Gcode_Plotter
import Interactive_Image_Control
import Main_GUI_Interface
import Maschine_Helper
import Process_GUI_Interface
import RotMotor_GUI_Interface
import Settings_Manager
import protocol_log
import theme
from PathManager import get_base_dir, get_gui_file_path, get_settings_path, migrate_user_data
from job_bridge import CoreProcessHandler
from machine_bridge import ArtisanFacade, MachineBridge, RotaryFacade, config_from_settings
from machine_safety_ui import MachineBar


def app_version():
    data = json.loads((get_base_dir() / "version.json").read_text(encoding="utf-8"))
    return f"{data['major']}.{data['minor']}.{data['patch']}"


def migrate(argv):
    """P4.1: user data into Documents/MachineControl/settings, once; `--migrate-from <folder>` imports from another
    folder (e.g. the v1.0 installation) – the files already in the user folder are moved to a backup first."""
    source = argv[argv.index("--migrate-from") + 1] if "--migrate-from" in argv[:-1] else None
    try:
        report = migrate_user_data(sources=[source] if source else None, force=bool(source))
    except OSError as e:
        report = f"User data could not be moved to the user folder: {e}"
    if report:
        protocol_log.note("app", report)
    return report


def build(argv=None, show_messages=True):
    """Everything the app consists of, wired together; the event loop is not started."""
    argv = list(sys.argv if argv is None else argv)
    protocol_log.setup()
    migration_report = migrate(argv)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    settings = Settings_Manager.SettingsManager(default_settings_path=get_settings_path("Default_Settings.json"),
                                                schema_path=get_settings_path("schema.json"), use_validation=False)
    theme.apply(app, settings.get("ui.theme", "dark"))  # Atelier look (P4.2) – before any window is shown
    gui = theme.load_ui(str(get_gui_file_path("Controller.ui")))
    gui.setWindowTitle(f"Artisan Controller {app_version()}")
    gui.show()
    if migration_report and show_messages:
        QtWidgets.QMessageBox.information(gui, "User data", migration_report)

    # controllers: the machine core runs in its own thread, the UI talks to it through the facades (P2.8)
    rot = RotaryFacade(settings=settings)
    bridge = MachineBridge(config=config_from_settings(settings), rotary=rot)
    artisan = ArtisanFacade(bridge, settings=settings)
    overview_camera = Camera_Controller.USBCameraController(settings=settings, camera_type="overview_camera")
    laser_camera = Camera_Controller.USBCameraController(settings=settings, camera_type="laser_camera")
    controllers = {"artisan_controller": artisan, "overview_camera_controller": overview_camera,
                   "laser_camera_controller": laser_camera, "rot_motor_controller": rot}
    # (the Arduino joystick stays switched off, C11: ArduinoController.ArduinoController(gui, artisan_controller=...))
    process_handler = CoreProcessHandler(gui, artisan, rot)

    # UI modules
    a = SimpleNamespace(app=app, gui=gui, settings=settings, rot=rot, bridge=bridge, artisan=artisan,
                        overview_camera=overview_camera, laser_camera=laser_camera, process_handler=process_handler)
    a.main_ui = Main_GUI_Interface.MainInterface(gui, controllers, settings)
    a.artisan_ui = Artisan_GUI_Interface.ArtisanInterface(gui, artisan)
    a.overview_camera_ui = Camera_GUI_Interface.CameraInterface(gui, settings, overview_camera)
    a.laser_camera_ui = Camera_GUI_Interface.CameraInterface(gui, settings, laser_camera)
    a.rot_ui = RotMotor_GUI_Interface.RotMotorInterface(gui, rot)
    a.process_ui = Process_GUI_Interface.ProcessInterface(gui, process_handler)
    a.image_control_laser = Interactive_Image_Control.InteractiveImageControl(gui, settings, a.laser_camera_ui, artisan)
    a.image_control_overview = Interactive_Image_Control.InteractiveImageControl(gui, settings, a.overview_camera_ui,
                                                                                 artisan)
    a.helper = Maschine_Helper.MaschineHelpers(gui, artisan)
    a.helper.setup_helpers()
    a.process_ui.stored_points = a.helper.stored_points  # step rotation from stored positions (P2.6)
    a.plotter = Gcode_Plotter.GCodePlotter(gui, process_handler)
    a.machine_bar = MachineBar(gui, artisan, settings=settings)  # machine state, Stop / E-stop (F9 / F12)

    def shutdown():
        """Laser off and stages stopped before the process ends."""
        bridge.shutdown()
        rot.disconnect()

    a.shutdown = shutdown
    app.aboutToQuit.connect(shutdown)
    return a


def main(argv=None):
    a = build(argv)
    return a.app.exec()


if __name__ == "__main__":
    sys.exit(main())
