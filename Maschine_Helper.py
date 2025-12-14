import numpy as np
from PyQt6 import uic
from PyQt6.QtWidgets import QListWidgetItem
from PathManager import get_gui_file_path

class MaschineHelpers():
    def __init__(self, gui, controller):
        self.gui = gui
        self.controller = controller
    
    def setup_helpers(self, circlefitter=True, rectanglefitter=True):
        if circlefitter:
            self.circle_fitter = CircleFitter(self.gui, self.controller)
        if rectanglefitter:
            self.rectangle_fitter = RectangleFitter(self.gui, self.controller)


class CircleFitter():
    def __init__(self, gui, controller):
        self.gui = gui
        self.controller = controller
        self.point_list = []
        self.circle_center = Point(None, None, None) # Point

        self.widget_path = str(get_gui_file_path("fit_point_item.ui"))

        #get the main controls for fitter
        self.circle_fit_listWidget = gui.circle_fit_listWidget
        self.circle_fit_add_point_button = gui.circle_fit_add_point_button
        self.goto_circle_center_button = gui.goto_circle_center_button
        self.circle_fit_x_spinbox = gui.circle_fit_x_spinbox
        self.circle_fit_y_spinbox = gui.circle_fit_y_spinbox
        self.circle_fit_z_spinbox = gui.circle_fit_z_spinbox

        self.circle_fit_add_point_button.clicked.connect(self.add_point)
        self.goto_circle_center_button.clicked.connect(self.got_to_center)

    def add_point(self):
        pos = self.controller.get_absolute_position()
        if pos is None:
            return
        point = Point(pos[0], pos[1], pos[2])
        self.point_list.append(point)

        # put widget it into the list
        widget = uic.loadUi(self.widget_path)
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.circle_fit_listWidget.addItem(item)
        self.circle_fit_listWidget.setItemWidget(item, widget)

        widget.abs_x_spinbox.setValue(point.X)
        widget.abs_y_spinbox.setValue(point.Y)
        widget.abs_z_spinbox.setValue(point.Z)

        widget.remove_button.clicked.connect(lambda _, p=point, w=widget: self.remove_point(p,w))
        widget.move_to_button.clicked.connect(lambda _, p=point: self.move_to_point(p))
        widget.set_current_pos_button.clicked.connect(lambda _, p=point, w=widget: self.set_current_point_pos(p,w))

        self.recalc_cicle_center()

    def remove_point(self, point, widget):
        """
        Remove a process step from the job handler and update the UI.
        :param index: Index of the process step to remove.
        """
        self.point_list.remove(point)
        
        for i in range(self.circle_fit_listWidget.count()):
            item = self.circle_fit_listWidget.item(i)
            if self.circle_fit_listWidget.itemWidget(item) is widget:
                self.circle_fit_listWidget.takeItem(i)
                # also remove from backend
                #del self.process_step_list[i]
                #self.process_step_list.remove(process_step)
                widget.deleteLater()
                break
        
        self.recalc_cicle_center()
    
    def set_current_point_pos(self, point, widget):
        new_pos = self.controller.get_absolute_position()

        point.set_pos(new_pos[0], new_pos[1], new_pos[2])

        widget.abs_x_spinbox.setValue(point.X)
        widget.abs_y_spinbox.setValue(point.Y)
        widget.abs_z_spinbox.setValue(point.Z)

        self.recalc_cicle_center()
    
    def got_to_center(self):
        self.controller.move_axis_absolute(self.circle_center.X, self.circle_center.Y, self.circle_center.Z, speed=30)

    def move_to_point(self, point):
        self.controller.move_axis_absolute(point.X, point.Y, point.Z, speed=30)


    def recalc_cicle_center(self):
        self.compute_circle_center_or_mean()
        if self.circle_center.X is None:
            self.goto_circle_center_button.setEnabled(False)
            self.circle_fit_x_spinbox.setValue(0)
            self.circle_fit_y_spinbox.setValue(0)
            self.circle_fit_z_spinbox.setValue(0)

        else:
            self.goto_circle_center_button.setEnabled(True)
            self.circle_fit_x_spinbox.setValue(self.circle_center.X)
            self.circle_fit_y_spinbox.setValue(self.circle_center.Y)
            self.circle_fit_z_spinbox.setValue(self.circle_center.Z)        

    # ---------- Fit function ----------

    def compute_circle_center_or_mean(self):
        """
        Returns:
        - None if no points
        - mean (x,y,z) if < 3 points
        - best-fit 3D circle center (x,y,z) if >= 3 points
        """
        points = self.convert_point_list_to_array()
        
        n = len(points)
        if n == 0:
            self.circle_center.set_pos(None, None, None)
            return
        if n < 3:
            # simple mean
            mid = points.mean(axis=0)
            self.circle_center.set_pos(mid[0], mid[1], mid[2])
            return

        # Step 1: fit plane via PCA
        centroid = points.mean(axis=0)
        X = points - centroid
        # covariance
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        # plane normal = smallest singular vector
        normal = Vt[-1, :]
        normal /= np.linalg.norm(normal) if np.linalg.norm(normal) > 0 else 1.0

        # Step 2: build 2D basis (u,v) spanning the plane
        # Pick arbitrary vector not parallel to normal
        ref = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        u = np.cross(normal, ref)
        nu = np.linalg.norm(u)
        if nu < 1e-12:
            # degenerate; choose another reference
            ref = np.array([0.0, 0.0, 1.0])
            u = np.cross(normal, ref)
            nu = np.linalg.norm(u)
        u /= nu
        v = np.cross(normal, u)

        # Step 3: project points to the plane 2D coords
        proj2d = np.column_stack([X @ u, X @ v])  # (n,2)

        # Step 4: 2D circle fit (algebraic least squares / Kåsa)
        c2d, r = self.fit_circle_2d_kasa(proj2d)
        if c2d is None or not np.isfinite(c2d).all():
            # fallback to mean if numeric issues
            return tuple(centroid.tolist())

        # Step 5: lift center back to 3D: centroid + c2d_x * u + c2d_y * v
        center3d = centroid + c2d[0] * u + c2d[1] * v
        self.circle_center.set_pos(center3d[0], center3d[1], center3d[2])
        return


    def fit_circle_2d_kasa(self, pts2: np.ndarray):
        """
        Kåsa algebraic fit: minimize ||Ax - b|| with
        For each (xi, yi): [2xi, 2yi, 1] * [a, b, c]^T = xi^2 + yi^2
        Center = (a, b), radius = sqrt(a^2 + b^2 + c)
        Robust enough for most UI use; you can swap for Pratt/Taubin if needed.
        """
        if pts2.shape[0] < 3:
            return None, None
        x = pts2[:, 0]
        y = pts2[:, 1]
        A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
        b = x * x + y * y
        try:
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            a, b0, c = sol
            r = np.sqrt(max(a * a + b0 * b0 + c, 0.0))
            return np.array([a, b0]), r
        except np.linalg.LinAlgError:
            return None, None
    
    def convert_point_list_to_array(self):
        list =[]
        for point in self.point_list:
            list.append([point.X, point.Y, point.Z])
        
        return np.array(list, dtype=float)
    
class RectangleFitter():
    def __init__(self, gui, controller):
        self.gui = gui
        self.controller = controller

        self.left_point = Point(None,None,None)
        self.right_point = Point(None,None,None)
        self.top_point = Point(None,None,None)
        self.bottom_point = Point(None,None,None)

        self.horz_center = Point(None,None,None)
        self.vert_center = Point(None,None,None)
        self.main_center = Point(None,None,None)


        self.rectangle_fit_listWidget = gui.rectangle_fit_listWidget
        gui.go_to_horz_center_button.clicked.connect(lambda _, i="horz": self.move_to_center(i))
        gui.go_to_vert_center_button.clicked.connect(lambda _, i="vert": self.move_to_center(i))
        gui.go_to_main_center_button.clicked.connect(lambda _, i="main": self.move_to_center(i))

        self.widget_path = str(get_gui_file_path("fit_point_item.ui"))

        self.setup_gui()
    
    def setup_gui(self):
        for text in ["LEFT:", "RIGHT:", "TOP:", "BOTTOM:"]:
            # put widget it into the list
            widget = uic.loadUi(self.widget_path)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.rectangle_fit_listWidget.addItem(item)
            self.rectangle_fit_listWidget.setItemWidget(item, widget)

            widget.abs_x_spinbox.setSpecialValueText("")
            widget.abs_y_spinbox.setSpecialValueText("")
            widget.abs_z_spinbox.setSpecialValueText("")

            widget.point_name_label.setText(text)
            widget.remove_button.setEnabled(False)
            widget.remove_button.setStyleSheet("background-color: transparent;")
            widget.move_to_button.clicked.connect(lambda _, i=text: self.move_to_fitpoint(i))
            widget.set_current_pos_button.clicked.connect(lambda _, i=text, w=widget: self.set_current_point_pos(i,w))
    
    def move_to_fitpoint(self, identifier):
        if identifier == "LEFT:":
            if self.left_point.X is not None:
                self.controller.move_axis_absolute(self.left_point.X, self.left_point.Y, self.left_point.Z, speed=30)
        elif identifier == "RIGHT:":
            if self.right_point.X is not None:
                self.controller.move_axis_absolute(self.right_point.X, self.right_point.Y, self.right_point.Z, speed=30)
        elif identifier == "TOP:":
            if self.top_point.X is not None:
                self.controller.move_axis_absolute(self.top_point.X, self.top_point.Y, self.top_point.Z, speed=30)
        elif identifier == "BOTTOM:":
            if self.bottom_point.X is not None:
                self.controller.move_axis_absolute(self.bottom_point.X, self.bottom_point.Y, self.bottom_point.Z, speed=30)
    
    def set_current_point_pos(self, identifier, widget):

        new_pos = self.controller.get_absolute_position()
        if new_pos is None:
            return
            
        if identifier == "LEFT:":
            self.left_point.set_pos(new_pos[0], new_pos[1], new_pos[2])
        elif identifier == "RIGHT:":
            self.right_point.set_pos(new_pos[0], new_pos[1], new_pos[2])
        elif identifier == "TOP:":
            self.top_point.set_pos(new_pos[0], new_pos[1], new_pos[2])
        elif identifier == "BOTTOM:":
            self.bottom_point.set_pos(new_pos[0], new_pos[1], new_pos[2])

        widget.abs_x_spinbox.setValue(new_pos[0])
        widget.abs_y_spinbox.setValue(new_pos[1])
        widget.abs_z_spinbox.setValue(new_pos[2])

        self.recalc_centers()

    def recalc_centers(self):
        if self.left_point.X is None and self.top_point is None:
            return #nothing to calculate
        
        if self.left_point.X and self.right_point.X:
            self.horz_center = self.calc_mid(self.left_point, self.right_point)
            self.gui.horz_center_x_spinbox.setValue(self.horz_center.X)
            self.gui.horz_center_y_spinbox.setValue(self.horz_center.Y)
            self.gui.horz_center_z_spinbox.setValue(self.horz_center.Z)
            self.gui.go_to_horz_center_button.setEnabled(True)
        
        if self.top_point.X and self.bottom_point.X:
            self.vert_center = self.calc_mid(self.top_point, self.bottom_point)
            self.gui.vert_center_x_spinbox.setValue(self.vert_center.X)
            self.gui.vert_center_y_spinbox.setValue(self.vert_center.Y)
            self.gui.vert_center_z_spinbox.setValue(self.vert_center.Z)
            self.gui.go_to_vert_center_button.setEnabled(True)
        
        if self.horz_center.X is not None and self.vert_center.X is not None:
            self.main_center = self.calc_mid(self.horz_center, self.vert_center)
            self.gui.main_center_x_spinbox.setValue(self.main_center.X)
            self.gui.main_center_y_spinbox.setValue(self.main_center.Y)
            self.gui.main_center_z_spinbox.setValue(self.main_center.Z)
            self.gui.go_to_main_center_button.setEnabled(True)
    
    def move_to_center(self, identifier):
        if identifier=="horz":
            if self.horz_center.X is not None:
                self.controller.move_axis_absolute(self.horz_center.X, self.horz_center.Y, self.horz_center.Z, speed=30)
        elif identifier=="vert":
            if self.vert_center.X is not None:
                self.controller.move_axis_absolute(self.vert_center.X, self.vert_center.Y, self.vert_center.Z, speed=30)
        elif identifier=="main":
            if self.main_center.X is not None:
                self.controller.move_axis_absolute(self.main_center.X, self.main_center.Y, self.main_center.Z, speed=30)
    
    def calc_mid(self, point1, point2):
        return Point((point1.X+point2.X)/2, (point1.Y+point2.Y)/2, (point1.Z+point2.Z)/2)

class Point():
    def __init__(self, x, y ,z):
        self.X = x
        self.Y = y
        self.Z = z
    
    def set_pos(self, x, y, z):
        self.X = x
        self.Y = y
        self.Z = z
