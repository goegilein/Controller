import cv2
from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import pyqtSignal, QObject
import datetime
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

        self.laser_camera_track_crosshair_button = gui.findChild(QtWidgets.QPushButton, "laser_camera_track_crosshair_button")

        #gui.test_button.clicked.connect(self.fit_image)

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

    def update_frame(self, frame):
        try:
            if frame is None or frame.size == 0:
                # empty frame often occurs on temporary camera startup failure
                return

            display_frame = frame.copy()
            if self.camera_type == "laser_camera" and self.laser_camera_track_crosshair_button.isChecked():
                output = self.detect_laser_cross_refined(display_frame)
                if output is not None:
                    display_frame = output

            frame_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            q_img = QtGui.QImage(frame_rgb.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
            self.pixmap_item.setPixmap(QtGui.QPixmap.fromImage(q_img))

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
            QtWidgets.QMessageBox.critical(self.gui, "Error", str(e))
            # timer is optional and may not exist in this object
            if hasattr(self, 'timer') and hasattr(self.timer, 'stop'):
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

    # def fit_image(self):
        

    #     """
    #     Robust sub-pixel center of a red laser cross (x, y).

    #     band_px:    half-thickness (pixels) of the horizontal/vertical fitting bands
    #     hi_percentile: percentile to find a coarse center
    #     band_percentile: percentile inside each band to keep only the strongest pixels
    #     """
    #     img = self.camera_controller.current_frame

    #     if img is None:
    #         QtWidgets.QMessageBox.warning(self.gui, "Warning", "No frame available to fit.")
    #         return



    #     r = img[:,:,2].astype(np.float32)
    #     g = img[:,:,1].astype(np.float32)
    #     b = img[:,:,0].astype(np.float32)
    #     red_dom = np.clip(r - 0.5*(g+b), 0, None).astype(np.uint8)

    #     file_path, _ = QtWidgets.QFileDialog.getSaveFileName(self.gui, "Save Image", "", "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)")
    #     if file_path:
    #         cv2.imwrite(file_path, red_dom)

    #     red_blur = cv2.GaussianBlur(red_dom, (5,5), 1.2)
    #     # auto Canny thresholds from median gradient
    #     v = np.median(red_blur)
    #     edges = cv2.Canny(red_blur, 0.66*v, 1.33*v)

    #     lines = cv2.HoughLines(edges, 1, np.pi/180, threshold=120)
    #     if lines is None:
    #         raise RuntimeError("No lines found")
    #     # choose near-horizontal and near-vertical
    #     best_h = max(lines[:,0,:], key=lambda lt: -abs(np.cos(lt[1])))
    #     best_v = max(lines[:,0,:], key=lambda lt: -abs(np.sin(lt[1])))
    #     rho_h, th_h = best_h
    #     rho_v, th_v = best_v

    #     A = np.array([[np.cos(th_h), np.sin(th_h)],
    #                 [np.cos(th_v), np.sin(th_v)]], float)
    #     b = np.array([rho_h, rho_v], float)
    #     x, y = np.linalg.solve(A, b)



    #     height, width = img.shape[0:2]

    #     if hasattr(self, 'cross_items2'):
    #             for item in self.cross_items:
    #                 self.camera_scene.removeItem(item)
    #                 self.cross_items2 = []
                    

    #     pen = QtGui.QPen(QtGui.QColor(1,0,0))
    #     pen.setWidth(2)
    #     h_line = QtWidgets.QGraphicsLineItem(0, int(y), width, int(y))
    #     v_line = QtWidgets.QGraphicsLineItem(int(x), 0, int(x), height)
    #     h_line.setPen(pen)
    #     v_line.setPen(pen)
    #     self.camera_scene.addItem(h_line)
    #     self.camera_scene.addItem(v_line)
    #     self.cross_items2 = [h_line, v_line]

    #     QtWidgets.QMessageBox.warning(self.gui, "Warning", f"X is {x} with: {float(x/width)}, Y is {y} with: {float(y/height)}")
    #     return float(x/width), float(y/height)  # sub-pixel center in image coordinates (0...1, 0...1)
    
    def detect_laser_cross_refined(self, img):
                
        output_img = img.copy()

        # 2. Convert to HSV color space
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 3. Create a strict mask for RED color
        # We use a high Saturation threshold (>100) to ignore the white glare completely
        # We use a high Value threshold (>100) to ignore dark red background noise
        lower_red_1 = np.array([0, 100, 100])
        upper_red_1 = np.array([10, 255, 255])
        mask1 = cv2.inRange(hsv, lower_red_1, upper_red_1)

        lower_red_2 = np.array([160, 100, 100])
        upper_red_2 = np.array([180, 255, 255])
        mask2 = cv2.inRange(hsv, lower_red_2, upper_red_2)

        red_mask = mask1 | mask2

        # 4. Clean up the mask to remove tiny specks of noise
        kernel = np.ones((3,3), np.uint8)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)

        # 5. Detect lines using Probabilistic Hough Transform
        # minLineLength=40 ensures we only care about long, distinct laser arms
        too_many_lines = True
        threshold = 200
        while too_many_lines:
            lines = cv2.HoughLinesP(
                red_mask, 
                rho=1, 
                theta=np.pi/180, 
                threshold=threshold, 
                minLineLength=50, 
                maxLineGap=200 # Bridge the massive white gap in the center
            )

            if lines is None:
                #print("No cross arms detected.")
                return output_img

            if threshold > 600:
                #print("Too many lines detected, even with high threshold. Consider adjusting parameters.")
                return output_img
            if len(lines) > 30:
                threshold += 10
            else:
                too_many_lines = False

        # 6. Group coordinates by orientation
        v_coords_x = []
        h_coords_y = []

        v_lines = []
        h_lines = []
        
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180.0 / np.pi)

            # Is it a vertical arm? (Angle near 90 degrees)
            if 70 < angle < 110:
                v_coords_x.extend([x1, x2])
                v_lines.append((x1, y1, x2, y2))
                
                cv2.line(output_img, (x1, y1), (x2, y2), (255, 0, 0), 1)
            # Is it a horizontal arm? (Angle near 0 or 180 degrees)
            elif angle < 20 or angle > 160:
                h_coords_y.extend([y1, y2])
                h_lines.append((x1, y1, x2, y2))

                cv2.line(output_img, (x1, y1), (x2, y2), (255, 255, 0), 1)

        not_enough_h_lines = False
        if len(h_lines) < 2:
            not_enough_h_lines = True
        if len(v_lines) < 4: # vertical lines are the one that give us the focal depth, without them we are basically lost, so we require at least 4 to be able to find the gap between them
            #print("Not enough lines detected to determine cross center.")
            return output_img

        # 7. Calculate the Median Intersection as a first guess for the center (Median is more robust to outliers than mean)
        # The median naturally ignores outliers (like a false line detected on the glare edge)
        center_x_guess, center_y_guess = None, None
        
        if v_coords_x:
            center_x_guess = int(np.median(v_coords_x))
        else:
            #print("No vertical lines detected.")
            return None
        if not not_enough_h_lines and h_coords_y:
            center_y_guess = int(np.median(h_coords_y))
        else:
            #print("No horizontal lines detected.")
            return None

        #8. Calculate all intersactions of vertical and horizontal lines that are close to the median guess (within 20 pixels), and use these to refine the center guess
        close_v_lines = [line for line in v_lines if abs(line[0] - center_x_guess) < 20 or abs(line[2] - center_x_guess) < 20]
        if not not_enough_h_lines:
            close_h_lines = [line for line in h_lines if abs(line[1] - center_y_guess) < 20 or abs(line[3] - center_y_guess) < 20]

        intersections_x = []
        intersections_y = []
        # for v_line in close_v_lines:
        #     for h_line in close_h_lines:
        #         x_inter,y_inter = get_intersection(v_line, h_line)
                
        #         intersections_x.append(x_inter)
        #         intersections_y.append(y_inter)


        #get the lines closest to the gap
        #get closest vertical lines
        for i, v_line in enumerate(close_v_lines):
            h_line = (0, center_y_guess, img.shape[1], center_y_guess) # A horizontal line through the center guess

            x_inter,y_inter = self.get_intersection(v_line, h_line)
            intersections_x.append([x_inter,i])
        
        sorted_x = sorted(intersections_x)
        gaps = [sorted_x[i+1][0] - sorted_x[i][0] for i in range(len(sorted_x)-1)]
        max_gap_index = np.argmax(gaps)

        v_line_1 = close_v_lines[sorted_x[max_gap_index][1]]
        v_line_2 = close_v_lines[sorted_x[max_gap_index + 1][1]]
        
        #get closest horizontal lines
        if not not_enough_h_lines:
            for i,h_line in enumerate(close_h_lines):
                v_line =(center_x_guess, 0, center_x_guess, img.shape[0]) # A vertical line through the center guess

                x_inter,y_inter = self.get_intersection(v_line, h_line)
                intersections_y.append([y_inter,i])
            sorted_y = sorted(intersections_y)
            gaps = [sorted_y[i+1][0] - sorted_y[i][0] for i in range(len(sorted_y)-1)]
            max_gap_index = np.argmax(gaps)
            
            h_line_1 = close_h_lines[sorted_y[max_gap_index][1]]
            h_line_2 = close_h_lines[sorted_y[max_gap_index + 1][1]]
        
            #find the intersections of the closest lines to get a refined center guess
            intersections_x = []
            intersections_y = []
            for v_line in [v_line_1, v_line_2]:
                for h_line in [h_line_1, h_line_2]:
                    x_inter,y_inter = self.get_intersection(v_line, h_line)
                    
                    intersections_x.append(x_inter)
                    intersections_y.append(y_inter)

            for line in [v_line_1, v_line_2, h_line_1, h_line_2]:
                x1, y1, x2, y2 = line
                cv2.line(output_img, (x1, y1), (x2, y2), (0, 0, 255), 2)

            # 9. Refine the center guess by taking the median of these intersections
            center_x_guess = int(np.mean(intersections_x))
            center_y_guess = int(np.mean(intersections_y))
        
        else: #no h_lines, only guess based on v_lines
            for v_line in [v_line_1, v_line_2]:
                center_x_guess = int((v_line[0] + v_line[2]) / 2)

  
        # 10. Draw the final result
        if center_x_guess is not None and center_y_guess is not None:
            center = (center_x_guess, center_y_guess)
            
            
            # Draw a bright green crosshair over the calculated center
            # cv2.circle(output_img, center, 8, (0, 255, 0), -1)
            cv2.line(output_img, (center_x_guess - 30, center_y_guess), (center_x_guess + 30, center_y_guess), (0, 255, 0), 2)
            cv2.line(output_img, (center_x_guess, center_y_guess - 30), (center_x_guess, center_y_guess + 30), (0, 255, 0), 2)
            
            #print(f"Precise cross center found at: {center}")

        return output_img
    
    def get_intersection(self, line1, line2):
        """
        Calculates the intersection point of two infinite lines.
        Line 1 is defined by (x1, y1) and (x2, y2).
        Line 2 is defined by (x3, y3) and (x4, y4).
        """

        x1, y1, x2, y2 = line1
        x3, y3, x4, y4 = line2
        # 1. Calculate the denominator
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        # 2. Check for parallel lines (denominator is 0)
        if d == 0:
            return None, None # Or raise an exception, depending on your needs
            
        # 3. Pre-calculate the cross products to avoid repeating operations
        cross_12 = (x1 * y2 - y1 * x2)
        cross_34 = (x3 * y4 - y3 * x4)
        
        # 4. Calculate the intersection point
        x_inter = (cross_12 * (x3 - x4) - (x1 - x2) * cross_34) / d
        y_inter = (cross_12 * (y3 - y4) - (y1 - y2) * cross_34) / d
        
        return x_inter, y_inter

class SignalEmitter(QObject):
    log_signal = pyqtSignal(str)
