import sys
import os
from pathlib import Path
from PyQt6 import QtWidgets, uic, QtCore
import Artisan_Controller
import Main_GUI_Interface
import Camera_Controller
import Camera_GUI_Interface
import Artisan_GUI_Interface
import ArduinoController
import Process_Handler
import Process_GUI_Interface
import Settings_Manager
import RotMotor_Cotroller
import RotMotor_GUI_Interface
import Interactive_Image_Control
import Maschine_Helper
import Gcode_Plotter

#first define paths
BASE_DIR = Path(__file__).resolve().parent
GUI_DIR = BASE_DIR / "GUI_files"
MAIN_GUI_PATH = GUI_DIR / "Controller.ui"
SETTINGS_DIR = BASE_DIR / "settings"
DEFAULT_SETTINGS_PATH = SETTINGS_DIR / "Default_Settings.json"
SCHEMA_PATH = SETTINGS_DIR / "schema.json"   

#setup QApplication and load GUI
app = QtWidgets.QApplication(sys.argv)
gui = uic.loadUi(MAIN_GUI_PATH)
gui.show()



#setup Settings Manager

settings = Settings_Manager.SettingsManager(default_settings_path=DEFAULT_SETTINGS_PATH, schema_path=SCHEMA_PATH, use_validation=False)


#setup controllers
#artisan_controller=Artisan_Controller.ArtisanController(connection_type="usb", port="COM6")
artisan_controller = Artisan_Controller.ArtisanController(settings=settings)
overview_camera_controller = Camera_Controller.USBCameraController(settings=settings, camera_type="overview_camera")
laser_camera_controller = Camera_Controller.USBCameraController(settings=settings, camera_type="laser_camera")
rot_motor_controller = RotMotor_Cotroller.RotMotorCotroller(settings=settings)
controllers={"artisan_controller":artisan_controller,
             "overview_camera_controller":overview_camera_controller, 
             "laser_camera_controller":laser_camera_controller,
             "rot_motor_controller":rot_motor_controller
             }

# arduino_controller = ArduinoController.ArduinoController(gui, artisan_controller=artisan_controller)
# arduino_controller.connect(port="COM5", baudrate=9600)
process_handler = Process_Handler.ProcessHandler(gui, artisan_controller)

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

gcode_plotter = Gcode_Plotter.GCodePlotter(gui, process_handler)


sys.exit(app.exec())


