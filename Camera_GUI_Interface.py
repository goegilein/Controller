import cv2
from PyQt6 import QtWidgets, uic, QtGui, QtCore
from PyQt6.QtCore import pyqtSignal, QObject
import datetime

class CameraInterface():
    def __init__(self, gui, camera_controller):
        super().__init__()
        self.camera_controller = camera_controller
        self.gui = gui

        self.OCam_View = gui.OCam_View
        self.OCam_scene = QtWidgets.QGraphicsScene()
        self.OCam_View.setScene(self.OCam_scene)
        self.pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self.OCam_scene.addItem(self.pixmap_item)

        self.OCam_start_button = gui.OCam_start_button
        self.OCam_start_button.clicked.connect(self.camera_controller.start_camera)

        self.OCam_stop_button = gui.OCam_stop_button
        self.OCam_stop_button.clicked.connect(self.camera_controller.stop_camera)

        #connect interface to camera controller callback to receive frames
        self.camera_controller.set_frame_changed_callback(self.update_frame)

        #logging for the camera
        self.log_textEdit=gui.log_textEdit
        self.log_emitter = SignalEmitter()
        self.log_emitter.log_signal.connect(self.append_log)
        self.camera_controller.set_log_callback(self.threadsafe_append_log)


    def update_frame(self,frame):
        try:
            # frame = self.camera_controller.capture_frame()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QtGui.QImage(frame.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
            self.pixmap_item.setPixmap(QtGui.QPixmap.fromImage(q_img))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self.timer.stop()
    
    def threadsafe_append_log(self, last_log):
        # This method is called from any thread
        self.log_emitter.log_signal.emit(last_log)
        
    def append_log(self, last_log):
        timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
        self.log_textEdit.appendPlainText(f"{timestamp}{last_log}")

class SignalEmitter(QObject):
    log_signal = pyqtSignal(str)
