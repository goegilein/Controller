import sys
import cv2
from PyQt6 import QtWidgets, uic, QtGui, QtCore
import time

class USBCameraController:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self._current_frame = None
        self.frame_changed_callback = None
        self.timer = QtCore.QTimer()
        self._frame_rate = 30

    @property
    def current_frame(self):
        return self._current_frame
    
    @current_frame.setter
    def current_frame(self, value):
        self._current_frame = value
        if self.frame_changed_callback:
            self.frame_changed_callback(value)
            
    def set_frame_changed_callback(self, callback):
        self.frame_changed_callback = callback 

    def connect(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise Exception("Could not open camera")
        else:
            self.start_camera()

    def capture_frame(self):
        if self.cap is None or not self.cap.isOpened():
            raise Exception("Camera is not opened")
        ret, self.current_frame = self.cap.read()
        if not ret:
            raise Exception("Failed to capture frame")
        #return frame
    
    def start_camera(self):
        try:
            if not self.cap or not self.cap.isOpened():
                print("Error: Camera not connected")
                return
            # self.camera_controller.connect()
            self.timer.timeout.connect(self.capture_frame)
            self.timer.start(self._frame_rate)  # Update frame every 30 ms
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def stop_camera(self):
        self.timer.stop()
        #time.sleep(self._frame_rate+0.01)

    def disconnect(self):
        self.stop_camera()
            
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def change_camera(self, camera_index):
        if self.cap:
            self.disconnect()
        self.camera_index = camera_index
    
    def set_frame_rate(self, frame_rate):
        self._frame_rate = frame_rate
        self.timer.setInterval(self._frame_rate)


    def __del__(self):
        self.disconnect()