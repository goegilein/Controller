import sys
import os
import json
from pathlib import Path
from PyQt6 import QtWidgets, uic, QtCore
import Main_GUI_Interface
import Camera_Controller
import Camera_GUI_Interface
import Artisan_GUI_Interface
import ArduinoController
import Process_GUI_Interface
import Settings_Manager
import RotMotor_GUI_Interface
import Interactive_Image_Control
import Maschine_Helper
import Gcode_Plotter
from PathManager import get_gui_file_path, get_settings_path, get_base_dir, migrate_user_data
import protocol_log
import theme
from machine_bridge import ArtisanFacade, MachineBridge, RotaryFacade, config_from_settings
from job_bridge import CoreProcessHandler
from machine_safety_ui import MachineBar

protocol_log.setup()

# P4.1: user data into Documents/MachineControl/settings, once; `--migrate-from <folder>` imports from another folder
# (e.g. the v1.0 installation) – the files already in the user folder are moved to a backup first
_migrate_from = sys.argv[sys.argv.index("--migrate-from") + 1] if "--migrate-from" in sys.argv[:-1] else None
try:
    MIGRATION_REPORT = migrate_user_data(sources=[_migrate_from] if _migrate_from else None, force=bool(_migrate_from))
except OSError as e:
    MIGRATION_REPORT = f"User data could not be moved to the user folder: {e}"
if MIGRATION_REPORT:
    protocol_log.note("app", MIGRATION_REPORT)

#Define paths using PathManager
MAIN_GUI_PATH = get_gui_file_path("Controller.ui")
DEFAULT_SETTINGS_PATH = get_settings_path("Default_Settings.json")
SCHEMA_PATH = get_settings_path("schema.json")   

#Load version
with open(get_base_dir() / "version.json") as f:
    version_data = json.load(f)
    version = f"{version_data['major']}.{version_data['minor']}.{version_data['patch']}"

#setup QApplication and load GUI
app = QtWidgets.QApplication(sys.argv)
gui = theme.load_ui(str(MAIN_GUI_PATH))
gui.setWindowTitle(f"Artisan Controller {version}")
gui.show()
if MIGRATION_REPORT:
    QtWidgets.QMessageBox.information(gui, "User data", MIGRATION_REPORT)



#setup Settings Manager

settings = Settings_Manager.SettingsManager(default_settings_path=DEFAULT_SETTINGS_PATH, schema_path=SCHEMA_PATH, use_validation=False)
theme.apply(app, settings.get("ui.theme", "dark"))  # Atelier look from BildHatcher, dark / bright (P4.2)


#setup controllers: the machine core runs in its own thread, the UI talks to it through the facades (v2.0, P2.8)
rot_motor_controller = RotaryFacade(settings=settings)
machine_bridge = MachineBridge(config=config_from_settings(settings), rotary=rot_motor_controller)
artisan_controller = ArtisanFacade(machine_bridge, settings=settings)
overview_camera_controller = Camera_Controller.USBCameraController(settings=settings, camera_type="overview_camera")
laser_camera_controller = Camera_Controller.USBCameraController(settings=settings, camera_type="laser_camera")
controllers={"artisan_controller":artisan_controller,
             "overview_camera_controller":overview_camera_controller, 
             "laser_camera_controller":laser_camera_controller,
             "rot_motor_controller":rot_motor_controller
             }

# arduino_controller = ArduinoController.ArduinoController(gui, artisan_controller=artisan_controller)
# arduino_controller.connect(port="COM5", baudrate=9600)
process_handler = CoreProcessHandler(gui, artisan_controller, rot_motor_controller)

#setup interfaces
main_interface=Main_GUI_Interface.MainInterface(gui, controllers, settings)
artisan_interface=Artisan_GUI_Interface.ArtisanInterface(gui, artisan_controller)
overview_camera_gui_interface = Camera_GUI_Interface.CameraInterface(gui, settings, overview_camera_controller)
laser_camera_gui_interface = Camera_GUI_Interface.CameraInterface(gui, settings, laser_camera_controller)
rot_mot_interface = RotMotor_GUI_Interface.RotMotorInterface(gui, rot_motor_controller)
process_gui_interface = Process_GUI_Interface.ProcessInterface(gui, process_handler)

#Maschine Helpers
interactive_image_control_lasercam = Interactive_Image_Control.InteractiveImageControl(gui, settings, laser_camera_gui_interface, artisan_controller)
interactive_image_control_overvoiew = Interactive_Image_Control.InteractiveImageControl(gui, settings, overview_camera_gui_interface, artisan_controller)

maschine_helper = Maschine_Helper.MaschineHelpers(gui, artisan_controller)
maschine_helper.setup_helpers()
process_gui_interface.stored_points = maschine_helper.stored_points  # step rotation from stored positions (P2.6)

gcode_plotter = Gcode_Plotter.GCodePlotter(gui, process_handler)

#machine state, Stop / E-stop (F9 / F12, with confirmation)
machine_bar = MachineBar(gui, artisan_controller, settings=settings)


def shutdown():
    """Laser off and stages stopped before the process ends."""
    machine_bridge.shutdown()
    rot_motor_controller.disconnect()


app.aboutToQuit.connect(shutdown)


sys.exit(app.exec())


