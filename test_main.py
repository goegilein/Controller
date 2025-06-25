import ArduinoController
import sys
from PyQt6 import QtWidgets, uic, QtCore
import os

arduino_controller = ArduinoController.ArduinoController()
arduino_controller.connect(port="COM5", baudrate=9600)


app = QtWidgets.QApplication(sys.argv)
base_path = os.path.dirname(os.path.abspath(__file__))
gui = uic.loadUi(os.path.join(base_path, "Controller.ui"))
gui.show()
sys.exit(app.exec())