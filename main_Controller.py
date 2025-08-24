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

settings = Settings_Manager.SettingsManager(default_settings_path=DEFAULT_SETTINGS_PATH, schema_path=SCHEMA_PATH, use_validation=True)


#setup controllers
#artisan_controller=Artisan_Controller.ArtisanController(connection_type="usb", port="COM6")
artisan_controller = Artisan_Controller.ArtisanController(settings=settings)
OCam_controller = Camera_Controller.USBCameraController(settings=settings, camera_type="overview_camera")
controllers={"artisan_controller":artisan_controller,"OCam_controller":OCam_controller}
# arduino_controller = ArduinoController.ArduinoController(gui, artisan_controller=artisan_controller)
# arduino_controller.connect(port="COM5", baudrate=9600)
process_handler = Process_Handler.ProcessHandler(gui, artisan_controller)

#setup interfaces
main_interface=Main_GUI_Interface.MainInterface(gui, controllers, settings)
artisan_interface=Artisan_GUI_Interface.ArtisanInterface(gui, artisan_controller)
OCam_gui_interface = Camera_GUI_Interface.CameraInterface(gui, OCam_controller) 
process_gui_interface = Process_GUI_Interface.ProcessInterface(gui, process_handler)


sys.exit(app.exec())


