import json
from pathlib import Path
import numpy as np
from PyQt6 import uic
from PyQt6.QtWidgets import QListWidgetItem, QApplication, QInputDialog, QLineEdit
from PathManager import get_gui_file_path, get_settings_path

class MaschineHelpers():
    def __init__(self, gui, controller):
        self.gui = gui
        self.controller = controller
    
    def setup_helpers(self, circlefitter=True, rectanglefitter=True, storedpoints=True, customsampleholders=True, stored_points_file=None):
        if circlefitter:
            self.circle_fitter = CircleFitter(self.gui, self.controller)
        if rectanglefitter:
            self.rectangle_fitter = RectangleFitter(self.gui, self.controller)
        if storedpoints:
            self.stored_points = StoredPoints(self.gui, self.controller, file_path=stored_points_file)
        if customsampleholders:
            self.custom_sample_holders = CustomSampleHolders(self.gui, self.controller, stored_points=getattr(self, "stored_points", None))



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
            self.main_center = Point(self.horz_center.X, self.vert_center.Y, (self.horz_center.Z + self.vert_center.Z)/2)
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


class CustomSampleHolders():
    def __init__(self, gui, controller, stored_points=None, file_path=None):
        self.gui = gui
        self.controller = controller
        self.stored_points = stored_points

        self.widget_path = str(get_gui_file_path("fit_point_item.ui"))
        if file_path is not None:
            self.file_path = Path(file_path)
        else:
            self.file_path = get_settings_path("custom_sample_holders.json", ensure_exists=True)

        self.holders_data = {}
        self.current_holder_name = None
        self.measured_points = {"Point1": None, "Point2": None, "Point3": None}

        self.rotation_matrix = None
        self.translation_vector = None
        self.transform_matrix = None
        self.measured_center = None

        # Resolve GUI widgets with fallback support (avoid 'or' on Qt containers as len(widget)==0 is Falsy)
        cb = getattr(gui, "custom_holders_combobox", None)
        if cb is None:
            cb = getattr(gui, "custom_holders_comobox", None)
        self.custom_holders_combobox = cb

        lw = getattr(gui, "custom_holders_listWidget", None)
        if lw is None:
            lw = getattr(gui, "custom_holder_listWidget", None)
        self.custom_holders_listWidget = lw

        self.ch_additional_x_label = getattr(gui, "ch_additional_x_label", None)
        self.ch_additional_y_label = getattr(gui, "ch_additional_y_label", None)
        self.ch_additional_z_label = getattr(gui, "ch_additional_z_label", None)

        self.ch_additional_x_spinbox = getattr(gui, "ch_additional_x_spinbox", None)
        self.ch_additional_y_spinbox = getattr(gui, "ch_additional_y_spinbox", None)
        self.ch_additional_z_spinbox = getattr(gui, "ch_additional_z_spinbox", None)

        self.ch_measured_x_spinbox = getattr(gui, "ch_measured_x_spinbox", None)
        self.ch_measured_y_spinbox = getattr(gui, "ch_measured_y_spinbox", None)
        self.ch_measured_z_spinbox = getattr(gui, "ch_measured_z_spinbox", None)

        self.ch_go_to_button = getattr(gui, "ch_go_to_button", None)
        self.ch_store_position_button = getattr(gui, "ch_store_position_button", None)

        # Configure spinbox ranges and decimals
        for sb in [self.ch_additional_x_spinbox, self.ch_additional_y_spinbox, self.ch_additional_z_spinbox]:
            if sb is not None:
                sb.setRange(-10000.0, 10000.0)
                sb.setDecimals(3)
                sb.setValue(0.0)

        for sb in [self.ch_measured_x_spinbox, self.ch_measured_y_spinbox, self.ch_measured_z_spinbox]:
            if sb is not None:
                sb.setRange(-10000.0, 10000.0)
                sb.setDecimals(3)
                sb.setSpecialValueText("")
                sb.setValue(sb.minimum())

        if self.ch_go_to_button is not None:
            self.ch_go_to_button.setEnabled(False)
            self.ch_go_to_button.clicked.connect(self.move_to_center)

        if self.ch_store_position_button is not None:
            self.ch_store_position_button.setEnabled(False)
            self.ch_store_position_button.clicked.connect(self.store_center_position)

        for sb in [self.ch_additional_x_spinbox, self.ch_additional_y_spinbox, self.ch_additional_z_spinbox]:
            if sb is not None:
                sb.valueChanged.connect(self.recalculate_workpiece_center)

        if self.custom_holders_combobox is not None:
            self.custom_holders_combobox.currentTextChanged.connect(self.on_holder_changed)

        self.load_holders_file()

    @property
    def stored_points_helper(self):
        if self.stored_points is not None:
            return self.stored_points
        return getattr(self.gui, "stored_points", None)

    def load_holders_file(self):
        if not self.file_path.exists():
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                self.holders_data = json.load(f)
        except Exception as e:
            print(f"Error loading custom sample holders from {self.file_path}: {e}")
            self.holders_data = {}

        if self.custom_holders_combobox is not None:
            self.custom_holders_combobox.blockSignals(True)
            self.custom_holders_combobox.clear()
            for name in self.holders_data.keys():
                self.custom_holders_combobox.addItem(name)
            self.custom_holders_combobox.blockSignals(False)
            if self.custom_holders_combobox.count() > 0:
                self.on_holder_changed(self.custom_holders_combobox.currentText())

    def on_holder_changed(self, holder_name):
        if not holder_name or holder_name not in self.holders_data:
            return
        self.current_holder_name = holder_name
        holder_cfg = self.holders_data[holder_name]

        labels = holder_cfg.get("Additional_Offset_Labels", {})
        if self.ch_additional_x_label is not None:
            self.ch_additional_x_label.setText(labels.get("X", "X (mm)"))
        if self.ch_additional_y_label is not None:
            self.ch_additional_y_label.setText(labels.get("Y", "Y (mm)"))
        if self.ch_additional_z_label is not None:
            self.ch_additional_z_label.setText(labels.get("Z", "Z (mm)"))

        for sb in [self.ch_additional_x_spinbox, self.ch_additional_y_spinbox, self.ch_additional_z_spinbox]:
            if sb is not None:
                sb.blockSignals(True)
                sb.setValue(0.0)
                sb.blockSignals(False)

        self.reset_center_display()
        self.setup_point_items(holder_cfg)

    def setup_point_items(self, holder_cfg):
        if self.custom_holders_listWidget is None:
            return
        self.custom_holders_listWidget.clear()
        self.measured_points = {"Point1": None, "Point2": None, "Point3": None}

        for pt_key in ["Point1", "Point2", "Point3"]:
            pt_data = holder_cfg.get(pt_key, {})
            pt_name = pt_data.get("Name", pt_key)

            widget = uic.loadUi(self.widget_path)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.custom_holders_listWidget.addItem(item)
            self.custom_holders_listWidget.setItemWidget(item, widget)

            widget.point_name_label.setText(pt_name)
            widget.remove_button.setEnabled(False)
            widget.remove_button.setStyleSheet("background-color: transparent;")

            widget.abs_x_spinbox.setSpecialValueText("")
            widget.abs_y_spinbox.setSpecialValueText("")
            widget.abs_z_spinbox.setSpecialValueText("")
            widget.abs_x_spinbox.setValue(widget.abs_x_spinbox.minimum())
            widget.abs_y_spinbox.setValue(widget.abs_y_spinbox.minimum())
            widget.abs_z_spinbox.setValue(widget.abs_z_spinbox.minimum())

            widget.set_current_pos_button.clicked.connect(lambda _, k=pt_key, w=widget: self.set_point_from_current_pos(k, w))
            widget.move_to_button.clicked.connect(lambda _, k=pt_key: self.move_to_measured_point(k))

    def set_point_from_current_pos(self, pt_key, widget):
        if self.controller is None:
            return
        pos = self.controller.get_absolute_position()
        if pos is None:
            return

        self.measured_points[pt_key] = np.array([pos[0], pos[1], pos[2]], dtype=float)

        widget.abs_x_spinbox.setValue(pos[0])
        widget.abs_y_spinbox.setValue(pos[1])
        widget.abs_z_spinbox.setValue(pos[2])

        if all(self.measured_points.get(k) is not None for k in ["Point1", "Point2", "Point3"]):
            self.calculate_transformation()

    def move_to_measured_point(self, pt_key):
        p = self.measured_points.get(pt_key)
        if p is not None and self.controller is not None:
            self.controller.move_axis_absolute(float(p[0]), float(p[1]), float(p[2]), speed=30)

    def calculate_transformation(self):
        if not self.current_holder_name or self.current_holder_name not in self.holders_data:
            return
        holder_cfg = self.holders_data[self.current_holder_name]
        try:
            p1 = holder_cfg["Point1"]
            p2 = holder_cfg["Point2"]
            p3 = holder_cfg["Point3"]
            P_local = np.array([
                [p1["X"], p1["Y"], p1["Z"]],
                [p2["X"], p2["Y"], p2["Z"]],
                [p3["X"], p3["Y"], p3["Z"]]
            ], dtype=float)
        except KeyError as e:
            print(f"CustomSampleHolders error: missing point coordinate in JSON: {e}")
            return

        P_mach = np.array([
            self.measured_points["Point1"],
            self.measured_points["Point2"],
            self.measured_points["Point3"]
        ], dtype=float)

        # Check for collinearity
        v1 = P_local[1] - P_local[0]
        v2 = P_local[2] - P_local[0]
        if np.linalg.norm(np.cross(v1, v2)) < 1e-6:
            print("CustomSampleHolders error: local points are collinear.")
            return

        w1 = P_mach[1] - P_mach[0]
        w2 = P_mach[2] - P_mach[0]
        if np.linalg.norm(np.cross(w1, w2)) < 1e-6:
            print("CustomSampleHolders error: measured machine points are collinear.")
            return

        centroid_local = np.mean(P_local, axis=0)
        centroid_mach = np.mean(P_mach, axis=0)

        p = P_local - centroid_local
        q = P_mach - centroid_mach

        H = p.T @ q
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T

        if np.linalg.det(R) < 0:
            Vt_corr = Vt.copy()
            Vt_corr[2, :] *= -1
            R = Vt_corr.T @ U.T

        t = centroid_mach - R @ centroid_local

        M = np.eye(4)
        M[:3, :3] = R
        M[:3, 3] = t

        self.rotation_matrix = R
        self.translation_vector = t
        self.transform_matrix = M

        self.recalculate_workpiece_center()

    def recalculate_workpiece_center(self):
        if self.rotation_matrix is None or self.translation_vector is None:
            return

        dx = self.ch_additional_x_spinbox.value() if self.ch_additional_x_spinbox is not None else 0.0
        dy = self.ch_additional_y_spinbox.value() if self.ch_additional_y_spinbox is not None else 0.0
        dz = self.ch_additional_z_spinbox.value() if self.ch_additional_z_spinbox is not None else 0.0

        offset_local = np.array([dx, dy, dz], dtype=float)
        offset_mach = self.rotation_matrix @ offset_local
        center_mach = self.translation_vector + offset_mach

        self.measured_center = center_mach

        if self.ch_measured_x_spinbox is not None:
            self.ch_measured_x_spinbox.setValue(float(center_mach[0]))
        if self.ch_measured_y_spinbox is not None:
            self.ch_measured_y_spinbox.setValue(float(center_mach[1]))
        if self.ch_measured_z_spinbox is not None:
            self.ch_measured_z_spinbox.setValue(float(center_mach[2]))

        if self.ch_go_to_button is not None:
            self.ch_go_to_button.setEnabled(True)
        if self.ch_store_position_button is not None:
            self.ch_store_position_button.setEnabled(True)

    def move_to_center(self):
        if self.measured_center is not None and self.controller is not None:
            self.controller.move_axis_absolute(
                float(self.measured_center[0]),
                float(self.measured_center[1]),
                float(self.measured_center[2]),
                speed=30
            )

    def store_center_position(self):
        if self.measured_center is None:
            return
        default_name = self.current_holder_name if self.current_holder_name else "Sample_Holder"
        name, ok = QInputDialog.getText(
            self.gui,
            "Store Position",
            "Enter position name:",
            QLineEdit.EchoMode.Normal,
            default_name
        )
        if ok and name.strip():
            pos_name = name.strip()
            helper = self.stored_points_helper
            if helper is not None:
                helper.add_point(
                    float(self.measured_center[0]),
                    float(self.measured_center[1]),
                    float(self.measured_center[2]),
                    name=pos_name
                )

    def reset_center_display(self):
        self.rotation_matrix = None
        self.translation_vector = None
        self.transform_matrix = None
        self.measured_center = None

        for sb in [self.ch_measured_x_spinbox, self.ch_measured_y_spinbox, self.ch_measured_z_spinbox]:
            if sb is not None:
                sb.setValue(sb.minimum())
                sb.setSpecialValueText("")

        if self.ch_go_to_button is not None:
            self.ch_go_to_button.setEnabled(False)
        if self.ch_store_position_button is not None:
            self.ch_store_position_button.setEnabled(False)


class StoredPoints():
    def __init__(self, gui=None, controller=None, list_widget=None, add_button=None, file_path=None):
        self.gui = gui
        self.controller = controller
        self.point_list = []

        stored_ui = get_gui_file_path("stored_position_item.ui")
        if stored_ui.exists():
            self.widget_path = str(stored_ui)
        else:
            self.widget_path = str(get_gui_file_path("fit_point_item.ui"))

        # Determine file path for stored points
        if file_path is not None:
            self.file_path = Path(file_path)
        else:
            # Check if stored_positions.json or stored_points.json exists, default to stored_positions.json
            pos_path = get_settings_path("stored_positions.json", ensure_exists=False)
            pts_path = get_settings_path("stored_points.json", ensure_exists=False)
            if pts_path.exists() and not pos_path.exists():
                self.file_path = pts_path
            else:
                self.file_path = get_settings_path("stored_positions.json", ensure_exists=True)

        # Main controls for stored points
        self.list_widget = list_widget
        if self.list_widget is None and gui is not None:
            self.list_widget = getattr(gui, "stored_position_listWidget", None) or getattr(gui, "stored_points_listWidget", None)

        self.stored_position_listWidget = self.list_widget

        self.add_point_button = add_button
        if self.add_point_button is None and gui is not None:
            self.add_point_button = getattr(gui, "add_stored_position_button", None) or getattr(gui, "add_stored_point_button", None)

        self.add_stored_position_button = self.add_point_button

        if self.add_point_button is not None:
            self.add_point_button.clicked.connect(lambda: self.add_point())

        # Load persisted points on startup
        self.load_from_file()

        # Connect to Qt application quit event if available
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.save_to_file)

    @property
    def points(self):
        """Access the list of stored points."""
        return self.point_list

    def get_points(self):
        """Return the list of stored Point objects."""
        return self.point_list

    def name_exists(self, name: str, exclude_point: "Point" = None) -> bool:
        """Check if a point name already exists (case-insensitive, trimmed)."""
        if not name:
            return False
        target = name.strip().lower()
        for p in self.point_list:
            if exclude_point is not None and p is exclude_point:
                continue
            if p.name and p.name.strip().lower() == target:
                return True
        return False

    def generate_unique_name(self, base_prefix: str = "Pos_") -> str:
        """Generate a guaranteed unique point name like Pos_1, Pos_2, etc."""
        idx = 1
        while self.name_exists(f"{base_prefix}{idx}"):
            idx += 1
        return f"{base_prefix}{idx}"

    def get_by_name(self, name: str) -> "Point":
        """Return the point matching the given name (case-insensitive), or None."""
        if not name:
            return None
        target = name.strip().lower()
        for p in self.point_list:
            if p.name and p.name.strip().lower() == target:
                return p
        return None

    def move_to_name(self, name: str):
        """Move machine controller to the point with the specified name."""
        point = self.get_by_name(name)
        if point is not None:
            self.move_to_point(point)

    def remove_by_name(self, name: str, save: bool = True) -> bool:
        """Remove a point by its unique name."""
        point = self.get_by_name(name)
        if point is not None:
            self.remove_point(point, save=save)
            return True
        return False

    def rename_point(self, old_name: str, new_name: str, save: bool = True) -> bool:
        """Safely rename a point, updating UI and persisting to disk."""
        point = self.get_by_name(old_name)
        if point is None:
            return False
        new_name = new_name.strip()
        if not new_name or self.name_exists(new_name, exclude_point=point):
            return False

        point.name = new_name
        if self.list_widget is not None:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                w = self.list_widget.itemWidget(item)
                if getattr(w, "point", None) is point:
                    if hasattr(w, "position_name_lineEdit"):
                        w.position_name_lineEdit.setText(new_name)
                    elif hasattr(w, "point_name_label"):
                        w.point_name_label.setText(new_name)
                    break

        if save:
            self.save_to_file()
        return True

    def add_current_position(self, name=None, save=True):
        """Add the current controller position as a stored point."""
        if self.controller is None:
            return None
        pos = self.controller.get_absolute_position()
        if pos is None:
            return None
        return self.add_point(pos[0], pos[1], pos[2], name=name, save=save)

    def add_point(self, x=None, y=None, z=None, name=None, save=True):
        """
        Add a point to the stored list.
        Can be called with coordinates (x, y, z), a Point object, a list/tuple of coords,
        dict, or with no arguments to capture the current controller position.
        
        :param x: X coordinate, Point object, coordinate tuple/list, dict, or None to capture current position.
        :param y: Y coordinate or None.
        :param z: Z coordinate or None.
        :param name: Unique text identifier for the point. Auto-generated if not provided.
        :param save: Whether to persist changes to the JSON file immediately (default True).
        :return: The created Point object, or None if capturing current position failed.
        """
        # If triggered by Qt clicked signal (passes boolean) or no args given, use current position
        if isinstance(x, bool) or (x is None and y is None and z is None):
            return self.add_current_position(name=name, save=save)

        # Handle passing a Point instance directly
        if isinstance(x, Point):
            pt_name = name if name is not None else getattr(x, "name", None)
            point = Point(x.X, x.Y, x.Z, name=pt_name)
        # Handle passing a list/tuple of coordinates [x, y, z]
        elif isinstance(x, (list, tuple)) and len(x) >= 3:
            point = Point(x[0], x[1], x[2], name=name)
        # Handle passing a dict
        elif isinstance(x, dict):
            point = Point.from_dict(x)
            if name is not None:
                point.name = name
        else:
            point = Point(x, y, z, name=name)

        # Enforce unique name
        if point.name is not None:
            clean_name = str(point.name).strip()
            if not clean_name:
                clean_name = self.generate_unique_name()
            elif self.name_exists(clean_name):
                base = clean_name
                idx = 1
                while self.name_exists(f"{base}_{idx}"):
                    idx += 1
                clean_name = f"{base}_{idx}"
            point.name = clean_name
        else:
            point.name = self.generate_unique_name()

        self.point_list.append(point)

        # Put widget into the list if a list widget is available
        if self.list_widget is not None:
            self._create_point_widget(point)

        if save:
            self.save_to_file()

        return point

    def _create_point_widget(self, point):
        """Create and configure the UI widget item for a point in the list widget."""
        widget = uic.loadUi(self.widget_path)
        widget.point = point
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

        if point.X is not None:
            widget.abs_x_spinbox.setValue(float(point.X))
        if point.Y is not None:
            widget.abs_y_spinbox.setValue(float(point.Y))
        if point.Z is not None:
            widget.abs_z_spinbox.setValue(float(point.Z))

        # Support stored_position_item.ui (QLineEdit)
        if hasattr(widget, "position_name_lineEdit"):
            widget.position_name_lineEdit.setText(str(point.name) if point.name else "")
            widget.position_name_lineEdit.setPlaceholderText("Position name")

            def on_name_text_changed(text):
                stripped = text.strip()
                if not stripped or self.name_exists(stripped, exclude_point=point):
                    widget.position_name_lineEdit.setStyleSheet("border: 1px solid red; background-color: #ffe6e6;")
                    widget.position_name_lineEdit.setToolTip("Name must be unique and non-empty")
                else:
                    widget.position_name_lineEdit.setStyleSheet("")
                    widget.position_name_lineEdit.setToolTip("")

            def on_name_editing_finished():
                new_name = widget.position_name_lineEdit.text().strip()
                if not new_name or self.name_exists(new_name, exclude_point=point):
                    # Revert to last valid name
                    widget.position_name_lineEdit.setText(point.name)
                    widget.position_name_lineEdit.setStyleSheet("")
                    widget.position_name_lineEdit.setToolTip("")
                else:
                    if new_name != point.name:
                        point.name = new_name
                        self.save_to_file()
                    widget.position_name_lineEdit.setStyleSheet("")
                    widget.position_name_lineEdit.setToolTip("")

            widget.position_name_lineEdit.textChanged.connect(on_name_text_changed)
            widget.position_name_lineEdit.editingFinished.connect(on_name_editing_finished)

        # Fallback support for fit_point_item.ui (QLabel)
        elif hasattr(widget, "point_name_label"):
            widget.point_name_label.setText(str(point.name) if point.name else "")

        widget.remove_button.clicked.connect(lambda _, p=point, w=widget: self.remove_point(p, w))
        widget.move_to_button.clicked.connect(lambda _, p=point: self.move_to_point(p))
        widget.set_current_pos_button.clicked.connect(lambda _, p=point, w=widget: self.set_current_point_pos(p, w))

        def on_x_changed():
            point.X = widget.abs_x_spinbox.value()
            self.save_to_file()

        def on_y_changed():
            point.Y = widget.abs_y_spinbox.value()
            self.save_to_file()

        def on_z_changed():
            point.Z = widget.abs_z_spinbox.value()
            self.save_to_file()

        widget.abs_x_spinbox.editingFinished.connect(on_x_changed)
        widget.abs_y_spinbox.editingFinished.connect(on_y_changed)
        widget.abs_z_spinbox.editingFinished.connect(on_z_changed)

        return widget

    def remove_point(self, point, widget=None, save=True):
        """Remove a point from the stored points list and update the UI list."""
        if point in self.point_list:
            self.point_list.remove(point)

        if self.list_widget is not None:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                item_widget = self.list_widget.itemWidget(item)
                if item_widget is widget or (widget is None and getattr(item_widget, "point", None) == point):
                    self.list_widget.takeItem(i)
                    if item_widget is not None:
                        item_widget.deleteLater()
                    break

        if save:
            self.save_to_file()

    def set_current_point_pos(self, point, widget, save=True):
        """Update the stored point with the current controller position."""
        if self.controller is None:
            return
        new_pos = self.controller.get_absolute_position()
        if new_pos is None:
            return

        point.set_pos(new_pos[0], new_pos[1], new_pos[2])

        widget.abs_x_spinbox.setValue(float(point.X))
        widget.abs_y_spinbox.setValue(float(point.Y))
        widget.abs_z_spinbox.setValue(float(point.Z))

        if save:
            self.save_to_file()

    def move_to_point(self, point):
        """Move the machine controller to the point position."""
        if self.controller is not None and point.X is not None and point.Y is not None and point.Z is not None:
            self.controller.move_axis_absolute(point.X, point.Y, point.Z, speed=30)

    def clear_points(self, save=True):
        """Clear all stored points and reset the UI list."""
        self.point_list.clear()
        if self.list_widget is not None:
            self.list_widget.clear()
        if save:
            self.save_to_file()

    def convert_point_list_to_array(self):
        """Convert stored points to a NumPy array of shape (N, 3)."""
        pts = [[p.X, p.Y, p.Z] for p in self.point_list if p.X is not None and p.Y is not None and p.Z is not None]
        return np.array(pts, dtype=float) if pts else np.empty((0, 3), dtype=float)

    def load_from_file(self, file_path=None):
        """Load stored points from JSON file into memory and UI."""
        path = Path(file_path) if file_path else self.file_path
        if path is None or not path.exists():
            return

        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return
            data = json.loads(text)
        except Exception as e:
            print(f"Error loading stored points from {path}: {e}")
            return

        # If data is a dict, check common keys or dictionary-keyed points
        if isinstance(data, dict):
            if "points" in data or "stored_positions" in data or "stored_points" in data:
                data = data.get("points") or data.get("stored_positions") or data.get("stored_points") or []
            else:
                # Format: {"Home": {"x": 0, "y": 0, "z": 0}}
                dict_list = []
                for k, v in data.items():
                    if isinstance(v, dict):
                        dict_list.append({"name": k, **v})
                    elif isinstance(v, (list, tuple)) and len(v) >= 3:
                        dict_list.append({"name": k, "x": v[0], "y": v[1], "z": v[2]})
                data = dict_list

        if not isinstance(data, list):
            return

        # Clear existing without writing to disk
        self.clear_points(save=False)

        for item in data:
            if isinstance(item, dict):
                x = item.get("x", item.get("X"))
                y = item.get("y", item.get("Y"))
                z = item.get("z", item.get("Z"))
                name = item.get("name", item.get("Name"))
                if x is not None and y is not None and z is not None:
                    clean_name = str(name).strip() if name is not None else ""
                    if not clean_name or self.name_exists(clean_name):
                        clean_name = self.generate_unique_name(base_prefix=clean_name + "_" if clean_name else "Pos_")
                    self.add_point(x, y, z, name=clean_name, save=False)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                self.add_point(item[0], item[1], item[2], save=False)

    def save_to_file(self, file_path=None):
        """Save current stored points to JSON file."""
        path = Path(file_path) if file_path else self.file_path
        if path is None:
            return

        data = []
        for p in self.point_list:
            if hasattr(p, "to_dict"):
                data.append(p.to_dict())
            else:
                pt_dict = {}
                if getattr(p, "name", None) is not None:
                    pt_dict["name"] = str(p.name)
                pt_dict["x"] = float(p.X) if p.X is not None else None
                pt_dict["y"] = float(p.Y) if p.Y is not None else None
                pt_dict["z"] = float(p.Z) if p.Z is not None else None
                data.append(pt_dict)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = path.with_suffix(path.suffix + ".tmp")
            temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(path)
        except Exception as e:
            try:
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as ex:
                print(f"Error saving stored points to {path}: {ex}")


class Point():
    def __init__(self, x=None, y=None, z=None, name=None):
        self.X = x
        self.Y = y
        self.Z = z
        self.name = name
    
    def set_pos(self, x, y, z):
        self.X = x
        self.Y = y
        self.Z = z

    def to_dict(self):
        d = {}
        if self.name is not None:
            d["name"] = str(self.name)
        d["x"] = float(self.X) if self.X is not None else None
        d["y"] = float(self.Y) if self.Y is not None else None
        d["z"] = float(self.Z) if self.Z is not None else None
        return d

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, (list, tuple)) and len(data) >= 3:
            return cls(data[0], data[1], data[2])
        x = data.get("x", data.get("X"))
        y = data.get("y", data.get("Y"))
        z = data.get("z", data.get("Z"))
        name = data.get("name", data.get("Name"))
        return cls(x, y, z, name=name)

    def __repr__(self):
        name_str = f", name='{self.name}'" if self.name is not None else ""
        return f"Point(X={self.X}, Y={self.Y}, Z={self.Z}{name_str})"

