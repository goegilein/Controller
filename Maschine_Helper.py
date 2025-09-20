import numpy as np
from PyQt6 import uic
from PyQt6.QtWidgets import QListWidgetItem

class MaschineHelpers():
    def __init__(self, gui, controller):
        self.gui = gui
        self.controller = controller
    
    def setup_helpers(self, circlefitter=True):
        if circlefitter:
            self.circle_fitter = CircleFitter(self.gui, self.controller)


class CircleFitter():
    def __init__(self, gui, controller):
        self.gui = gui
        self.controller = controller
        self.point_list = []
        self.circle_center = Point(None, None, None) # Point

        self.widget_path = "GUI_files/fit_point_item.ui"

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
        self.controller. move_axis_absolute(self.circle_center.X, self.circle_center.Y, self.circle_center.Z, speed=30)

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
        
    
class Point():
    def __init__(self, x, y ,z):
        self.X = x
        self.Y = y
        self.Z = z
    
    def set_pos(self, x, y, z):
        self.X = x
        self.Y = y
        self.Z = z
