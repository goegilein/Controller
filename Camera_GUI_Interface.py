import cv2
from PyQt6 import QtWidgets, uic, QtGui, QtCore
from PyQt6.QtCore import pyqtSignal, QObject
import datetime
import PIL.Image as Image
import numpy as np
import cv2

class CameraInterface():
    def __init__(self, gui, settings, camera_controller):
        super().__init__()
        self.gui = gui
        self.s = settings
        self.camera_controller = camera_controller
        self.camera_type = self.camera_controller.camera_type
        self.load_settings()
        

        self.camera_view = gui.findChild(QtWidgets.QGraphicsView, self.camera_type+"_view")
        self.camera_scene = QtWidgets.QGraphicsScene()
        self.camera_view.setScene(self.camera_scene)
        self.pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self.camera_scene.addItem(self.pixmap_item)

        self.camera_start_button = gui.findChild(QtWidgets.QPushButton, self.camera_type+"_start_button")
        self.camera_start_button.clicked.connect(self.camera_controller.start_camera)

        self.camera_stop_button = gui.findChild(QtWidgets.QPushButton, self.camera_type+"_stop_button")
        self.camera_stop_button.clicked.connect(self.camera_controller.stop_camera)

        self.camera_save_image_button = gui.findChild(QtWidgets.QPushButton, self.camera_type+"_save_image_button")
        self.camera_save_image_button.clicked.connect(self.save_image)

        gui.test_button.clicked.connect(self.fit_image)

        #connect interface to camera controller callback to receive frames
        self.camera_controller.set_frame_changed_callback(self.update_frame)

        #logging for the camera
        self.log_textEdit=gui.log_textEdit
        self.log_emitter = SignalEmitter()
        self.log_emitter.log_signal.connect(self.append_log)
        self.camera_controller.set_log_callback(self.threadsafe_append_log)

         #Callbacks for Setting changes
        settings.settingChanged.connect(self.load_settings)  # Reload settings if they change
        settings.settingsReplaced.connect(self.load_settings)  # Reload settings if they are replaced
    
    def load_settings(self):
        """Load settings from the SettingsManager."""
        self.crosshair_active = self.s.get(self.camera_type + ".crosshair_overlay.active", False)
        self.crosshair_horizontal = self.s.get(self.camera_type + ".crosshair_overlay.horizontal_position", 0.5)
        self.crosshair_vertical = self.s.get(self.camera_type + ".crosshair_overlay.vertical_position", 0.5)
        self.crosshair_color = self.s.get(self.camera_type + ".crosshair_overlay.color", "green")
        self.crosshair_thickness = self.s.get(self.camera_type + ".crosshair_overlay.thickness", 2)   

    def update_frame(self,frame):
        try:
            # frame = self.camera_controller.capture_frame()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QtGui.QImage(frame.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
            self.pixmap_item.setPixmap(QtGui.QPixmap.fromImage(q_img))

            # Draw overview if selected

            # Remove previous cross items if they exist
            if hasattr(self, 'cross_items'):
                for item in self.cross_items:
                    self.camera_scene.removeItem(item)
                    self.cross_items = []
                    
            if self.crosshair_active:
                pen = QtGui.QPen(QtGui.QColor(*self.crosshair_color))
                pen.setWidth(self.crosshair_thickness)
                v_pos = int(height * self.crosshair_horizontal)
                h_pos = int(width * self.crosshair_vertical)
                h_line = QtWidgets.QGraphicsLineItem(0, v_pos, width, v_pos)
                v_line = QtWidgets.QGraphicsLineItem(h_pos, 0, h_pos, height)
                h_line.setPen(pen)
                v_line.setPen(pen)
                self.camera_scene.addItem(h_line)
                self.camera_scene.addItem(v_line)
                self.cross_items = [h_line, v_line]
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self.timer.stop()

    def save_image(self):
        frame = self.camera_controller.current_frame
        if frame is not None:
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(self.gui, "Save Image", "", "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)")
            if file_path:
                cv2.imwrite(file_path, frame)
        else:
            QtWidgets.QMessageBox.warning(self.gui, "Warning", "No frame available to save.")
    
    def threadsafe_append_log(self, last_log):
        # This method is called from any thread
        self.log_emitter.log_signal.emit(last_log)
        
    def append_log(self, last_log):
        timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
        self.log_textEdit.appendPlainText(f"{timestamp}{last_log}")

    def fit_image(self):
        

        """
        Robust sub-pixel center of a red laser cross (x, y).

        band_px:    half-thickness (pixels) of the horizontal/vertical fitting bands
        hi_percentile: percentile to find a coarse center
        band_percentile: percentile inside each band to keep only the strongest pixels
        """
        img = self.camera_controller.current_frame

        if img is None:
            QtWidgets.QMessageBox.warning(self.gui, "Warning", "No frame available to fit.")
            return



        r = img[:,:,2].astype(np.float32)
        g = img[:,:,1].astype(np.float32)
        b = img[:,:,0].astype(np.float32)
        red_dom = np.clip(r - 0.5*(g+b), 0, None).astype(np.uint8)

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(self.gui, "Save Image", "", "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)")
        if file_path:
            cv2.imwrite(file_path, red_dom)

        red_blur = cv2.GaussianBlur(red_dom, (5,5), 1.2)
        # auto Canny thresholds from median gradient
        v = np.median(red_blur)
        edges = cv2.Canny(red_blur, 0.66*v, 1.33*v)

        lines = cv2.HoughLines(edges, 1, np.pi/180, threshold=120)
        if lines is None:
            raise RuntimeError("No lines found")
        # choose near-horizontal and near-vertical
        best_h = max(lines[:,0,:], key=lambda lt: -abs(np.cos(lt[1])))
        best_v = max(lines[:,0,:], key=lambda lt: -abs(np.sin(lt[1])))
        rho_h, th_h = best_h
        rho_v, th_v = best_v

        A = np.array([[np.cos(th_h), np.sin(th_h)],
                    [np.cos(th_v), np.sin(th_v)]], float)
        b = np.array([rho_h, rho_v], float)
        x, y = np.linalg.solve(A, b)



        height, width = img.shape[0:2]

        if hasattr(self, 'cross_items2'):
                for item in self.cross_items:
                    self.camera_scene.removeItem(item)
                    self.cross_items2 = []
                    

        pen = QtGui.QPen(QtGui.QColor(1,0,0))
        pen.setWidth(2)
        h_line = QtWidgets.QGraphicsLineItem(0, int(y), width, int(y))
        v_line = QtWidgets.QGraphicsLineItem(int(x), 0, int(x), height)
        h_line.setPen(pen)
        v_line.setPen(pen)
        self.camera_scene.addItem(h_line)
        self.camera_scene.addItem(v_line)
        self.cross_items2 = [h_line, v_line]

        QtWidgets.QMessageBox.warning(self.gui, "Warning", f"X is {x} with: {float(x/width)}, Y is {y} with: {float(y/height)}")
        return float(x/width), float(y/height)  # sub-pixel center in image coordinates (0...1, 0...1)

class SignalEmitter(QObject):
    log_signal = pyqtSignal(str)
