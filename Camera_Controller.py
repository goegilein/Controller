import sys
import cv2
from PyQt6 import QtWidgets, uic, QtGui, QtCore
import time

class USBCameraController:
    def __init__(self, camera_index=-1):
        self.camera_index = camera_index
        self.camera_name = f"Camera {camera_index}"
        self.cap = None
        self.connected = False
        self._current_frame = None
        self.frame_changed_callback = None
        self.timer = QtCore.QTimer()
        self._frame_rate = 30
        self._last_log = ''

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

    @property
    def last_log(self):
        return self._last_log
    
    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        if self.log_callback:
            self.log_callback(value)

    def set_log_callback(self, callback):
        self.log_callback = callback

    def connect(self):
        try:
            if self.camera_index < 0:
                raise ValueError("No Camera selected for connection.")
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                self.connected = False
                raise Exception(f"Error connecting to camera:Could not open camera {self.camera_name}")
            else:
                self.connected = True
                self.last_log = f"Camera {self.camera_name} connected successfully."
                self.start_camera()
        except Exception as e:
            self.last_log = f"{str(e)}"

    def capture_frame(self):
        if self.cap is None or not self.cap.isOpened():
            raise Exception(f"Camera {self.camera_name} is not opened")
        ret, self.current_frame = self.cap.read()
        if not ret:
            raise Exception(f"Failed to capture frame on camera {self.camera_name}")
        #return frame
    
    def start_camera(self):
        try:
            if not self.cap or not self.cap.isOpened():
                self.last_log = f"Camera {self.camera_name} is not connected."
                return
            # self.camera_controller.connect()
            self.timer.timeout.connect(self.capture_frame)
            self.timer.start(self._frame_rate)  # Update frame every 30 ms
            self.last_log = f"Camera {self.camera_name} started with frame rate {self._frame_rate} ms."
        except Exception as e:
            self.last_log = f"Error starting the camera: {str(e)}"

    def stop_camera(self):
        if self.timer.isActive():
            self.timer.stop()
            self.last_log = f"Camera {self.camera_name} stopped."

    def disconnect(self):
        self.stop_camera()
            
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
            self.cap = None
            self.connected = False
            self.last_log = f"Camera {self.camera_name} disconnected."
    
    def change_camera(self, camera_index, camera_name=None):
        if self.connected:
            self.disconnect()

        self.camera_index = camera_index

        if camera_name:
            self.camera_name = camera_name
        else:
            self.camera_name = f"Camera {camera_index}"
    
    def set_frame_rate(self, frame_rate):
        self._frame_rate = frame_rate
        self.timer.setInterval(self._frame_rate)


    def __del__(self):
        self.disconnect()