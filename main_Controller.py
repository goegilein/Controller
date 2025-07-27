import sys
import os
from PyQt6 import QtWidgets, uic, QtCore
import Artisan_Controller
import Main_GUI_Interface
import Camera_Controller
import Camera_GUI_Interface
import Artisan_GUI_Interface
import ArduinoController
import Process_Handler
import Process_GUI_Interface

app = QtWidgets.QApplication(sys.argv)
base_path = os.path.dirname(os.path.abspath(__file__))
gui = uic.loadUi(os.path.join(base_path, "GUI_files/Controller.ui"))
gui.show()

#setup controllers
artisan_controller=Artisan_Controller.ArtisanController(connection_type="usb", port="COM6")
OCam_controller = Camera_Controller.USBCameraController()
controllers={"artisan_controller":artisan_controller,"OCam_controller":OCam_controller}
# arduino_controller = ArduinoController.ArduinoController(gui, artisan_controller=artisan_controller)
# arduino_controller.connect(port="COM5", baudrate=9600)
process_handler = Process_Handler.ProcessHandler(gui, artisan_controller)

#setup interfaces
main_interface=Main_GUI_Interface.MainInterface(gui, controllers)
artisan_interface=Artisan_GUI_Interface.ArtisanInterface(gui, artisan_controller)
OCam_gui_interface = Camera_GUI_Interface.CameraInterface(gui, OCam_controller) 
process_gui_interface = Process_GUI_Interface.ProcessInterface(gui, process_handler)


sys.exit(app.exec())