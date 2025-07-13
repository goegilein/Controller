from PyQt6 import QtWidgets, uic, QtCore
from BaseClasses import BaseClass
import os
import wmi


class MainInterface(BaseClass):
    def __init__(self, gui, controllers):
        super().__init__()
        self.gui = gui
        self.controllers=controllers
        self.artisan_controller = controllers["artisan_controller"]
        self.OCam_controller = controllers["OCam_controller"]

        # Store the options window as an instance attribute
        self.connection_status_window = None
        
        #SET MENU BAR ACTIONS HERE!!
        self.connect_all_action=gui.connect_all_action
        self.disconnect_all_action=gui.disconnect_all_action
        self.connect_all_action.triggered.connect(self.connect_all)
        self.disconnect_all_action.triggered.connect(self.disconnect_all)
        self.connection_status_action=gui.connection_status_action
        self.connection_status_action.triggered.connect(self.show_connection_status)

    def connect_all(self):
        self.artisan_controller.connect()
        self.OCam_controller.connect()

    def disconnect_all(self):
        self.artisan_controller.disconnect()
        self.OCam_controller.disconnect()
    
    def show_connection_status(self):
        if self.connection_status_window:
            self.connection_status_window.close()
        self.connection_status_window = ConnectionStatusWindow(self.controllers)
        self.connection_status_window.show()

class ConnectionStatusWindow(QtWidgets.QWidget):
    def __init__(self, controllers):       
        super().__init__()
        base_path = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(base_path, "connection_status_window.ui")
        gui=uic.loadUi(ui_path, self)

        #controllers
        self.artisan_controller = controllers["artisan_controller"]
        self.OCam_controller = controllers["OCam_controller"]

        #artisan connect gui
        self.artisan_port_lineEdit = gui.artisan_port_lineEdit
        self.artisan_connect_button = gui.artisan_connect_button
        self.artisan_connect_label = gui.artisan_connect_label

        self.artisan_connect_button.clicked.connect(lambda: self.connect_disconnect(self.artisan_controller))
        self.artisan_port_lineEdit.textChanged.connect(lambda: self.set_port(self.artisan_controller))
        
        #OCam connect gui
        self.OCam_connect_button = gui.OCam_connect_button
        self.OCam_connect_label = gui.OCam_connect_label
        self.OCam_select_comboBox = gui.OCam_select_comboBox
        #self.OCam_select_comboBox.addItems([f"Camera {i}" for i in range(5)]) #need to change this to get items
        self.populate_camera_list(self.OCam_select_comboBox)
        
        self.OCam_connect_button.clicked.connect(lambda: self.connect_disconnect(self.OCam_controller))
        self.OCam_select_comboBox.currentIndexChanged.connect(lambda: self.change_camera(self.OCam_controller))
        
        
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
        
        #Overview Camera (OCam)
        self.OCam_select_comboBox.setCurrentIndex(self.OCam_controller.camera_index+1)  # +1 to account for the placeholder
        if self.OCam_controller.connected:
            self.OCam_connect_button.setText('disconnect')
            self.OCam_connect_label.setText(f'Connected on Camera {self.OCam_controller.camera_index}')
            self.OCam_connect_label.setStyleSheet("color: green;")
        else:
            self.OCam_connect_button.setText('connect')
            self.OCam_connect_label.setText('Disconnected')
            self.OCam_connect_label.setStyleSheet("color: red;")
    
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
        self.OCam_select_comboBox.clear()
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



        
        
    