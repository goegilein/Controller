from PyQt6 import QtWidgets, uic, QtCore
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from Settings_Binder import SettingsEditorWidget
from Settings_Manager import SettingsManager
from BaseClasses import BaseClass
from pathlib import Path
import os
import wmi


class MainInterface(BaseClass):
    def __init__(self, gui, controllers, settings: SettingsManager):
        super().__init__()
        self.gui = gui
        self.controllers=controllers
        self.sm = settings
        self.artisan_controller = controllers["artisan_controller"]
        self.overview_camera_controller = controllers["overview_camera_controller"]
        self.laser_camera_controller = controllers["laser_camera_controller"]

        # Store the options window as an instance attribute
        self.connection_status_window = None
        
        #SET MENU BAR ACTIONS HERE!!
        self.connect_all_action=gui.connect_all_action
        self.disconnect_all_action=gui.disconnect_all_action
        self.connect_all_action.triggered.connect(self.connect_all)
        self.disconnect_all_action.triggered.connect(self.disconnect_all)
        self.connection_status_action=gui.connection_status_action
        self.connection_status_action.triggered.connect(self.show_connection_status)

        self.edit_settings_action = gui.edit_settings_action
        self.edit_settings_action.triggered.connect(self.open_settings_dialog)

        #Signal connections
        self.sm.settingValidationError.connect(self._on_validation_error)

    def connect_all(self):
        self.artisan_controller.connect()
        self.overview_camera_controller.connect()
        self.laser_camera_controller.connect()

    def disconnect_all(self):
        self.artisan_controller.disconnect()
        self.overview_camera_controller.disconnect()
        self.laser_camera_controller.disconnect()
    
    def show_connection_status(self):
        if self.connection_status_window:
            self.connection_status_window.close()
        self.connection_status_window = ConnectionStatusWindow(self.controllers)
        self.connection_status_window.show()
    
    def open_settings_dialog(self):
        dlg = QDialog()
        dlg.setWindowTitle("Settings")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0,0,0,0)
        BASE_DIR = Path(__file__).resolve().parent
        GUI_DIR = BASE_DIR / "GUI_files"
        SETTINGS_GUI_PATH = GUI_DIR / "Settings_widget.ui"
        lay.addWidget(SettingsEditorWidget(self.sm, SETTINGS_GUI_PATH, parent=dlg))
        dlg.resize(700, 800)
        dlg.exec()
    
    def _on_validation_error(self, error):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Settings Validation Error")
        msg.setText(f"There was an error validating the settings:")
        msg.setDetailedText(str(error))
        msg.exec()

class ConnectionStatusWindow(QtWidgets.QWidget):
    def __init__(self, controllers):       
        super().__init__()
        base_path = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(base_path, "GUI_files/connection_status_window.ui")
        gui=uic.loadUi(ui_path, self)

        #controllers
        self.artisan_controller = controllers["artisan_controller"]
        self.overview_camera_controller = controllers.get("overview_camera_controller", None)  # Optional
        self.laser_camera_controller = controllers.get("laser_camera_controller", None)  # Optional

        #artisan connect gui
        self.artisan_port_lineEdit = gui.artisan_port_lineEdit
        self.artisan_connect_button = gui.artisan_connect_button
        self.artisan_connect_label = gui.artisan_connect_label

        self.artisan_connect_button.clicked.connect(lambda: self.connect_disconnect(self.artisan_controller))
        self.artisan_port_lineEdit.textChanged.connect(lambda: self.set_port(self.artisan_controller))
        
        #overview_camera connect gui
        self.overview_camera_connect_button = gui.overview_camera_connect_button
        self.overview_camera_connect_label = gui.overview_camera_connect_label
        self.overview_camera_select_comboBox = gui.overview_camera_select_comboBox
        self.populate_camera_list(self.overview_camera_select_comboBox)
        
        self.overview_camera_connect_button.clicked.connect(lambda: self.connect_disconnect(self.overview_camera_controller))
        self.overview_camera_select_comboBox.currentIndexChanged.connect(lambda: self.change_camera(self.overview_camera_controller))

        #Laser connect gui
        self.laser_camera_connect_button = gui.laser_camera_connect_button
        self.laser_camera_connect_label = gui.laser_camera_connect_label
        self.laser_camera_select_comboBox = gui.laser_camera_select_comboBox
        self.populate_camera_list(self.laser_camera_select_comboBox)
        
        self.laser_camera_connect_button.clicked.connect(lambda: self.connect_disconnect(self.laser_camera_controller))
        self.laser_camera_select_comboBox.currentIndexChanged.connect(lambda: self.change_camera(self.laser_camera_controller))
        
        
        self.update_gui()

    def update_gui(self):
        #artisan
        self.artisan_port_lineEdit.setText(self.artisan_controller.port)
        if self.artisan_controller.is_connection_active():
            self.artisan_connect_button.setText('disconnect')
            self.artisan_connect_label.setText(f'Connected on {self.artisan_controller.port}')
            self.artisan_connect_label.setStyleSheet("color: green;")
        else:
            self.artisan_connect_button.setText('connect')
            self.artisan_connect_label.setText('Disconnected')
            self.artisan_connect_label.setStyleSheet("color: red;")
        
        #Overview Camera (Overview Camera)
        self.overview_camera_select_comboBox.setCurrentIndex(self.overview_camera_controller.camera_index+1)  # +1 to account for the placeholder
        if self.overview_camera_controller.connected:
            self.overview_camera_connect_button.setText('disconnect')
            self.overview_camera_connect_label.setText(f'Connected on Camera {self.overview_camera_controller.camera_index}')
            self.overview_camera_connect_label.setStyleSheet("color: green;")
        else:
            self.overview_camera_connect_button.setText('connect')
            self.overview_camera_connect_label.setText('Disconnected')
            self.overview_camera_connect_label.setStyleSheet("color: red;")

        #Laser Camera (Laser Camera)
        self.laser_camera_select_comboBox.setCurrentIndex(self.laser_camera_controller.camera_index+1)  # +1 to account for the placeholder
        if self.laser_camera_controller.connected:
            self.laser_camera_connect_button.setText('disconnect')
            self.laser_camera_connect_label.setText(f'Connected on Camera {self.laser_camera_controller.camera_index}')
            self.laser_camera_connect_label.setStyleSheet("color: green;")
        else:
            self.laser_camera_connect_button.setText('connect')
            self.laser_camera_connect_label.setText('Disconnected')
            self.laser_camera_connect_label.setStyleSheet("color: red;")
    
    def connect_disconnect(self,controller):
        sender=self.sender()
        if sender.text() == 'connect':
            controller.connect()
        else:
            controller.disconnect()
        self.update_gui()
    
    def set_port(self,controller):
        sender=self.sender()
        controller.port=sender.text()
    
    def populate_camera_list(self, combobox):
        combobox.clear()
        c = wmi.WMI()
        available_cameras = ['None']
        # 'usbvideo' is the service name for USB Video Class devices
        for dev in c.Win32_PnPEntity(Service="usbvideo"):
            available_cameras.append(dev.Name)

        if not available_cameras:
            available_cameras = ["No cameras found"]
        combobox.addItems(available_cameras)
    
    def change_camera(self, controller):
        sender = self.sender()
        #controller.camera_index = sender.currentIndex()
        controller.change_camera(sender.currentIndex()-1, sender.currentText()) # use index - 1 to skip the placeholder



        
        
    