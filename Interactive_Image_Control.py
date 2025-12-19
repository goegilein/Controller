import numpy as np
from typing import Tuple, Optional, Dict
from PyQt6 import QtWidgets, QtCore, QtGui, uic
from pathlib import Path
from PathManager import get_gui_file_path

class InteractiveImageControl(QtCore.QObject):
    def __init__(self, gui, settings, camera_GUI, artisan_controller):
        super().__init__()
        self.gui = gui
        self.s = settings
        self.camera_GUI = camera_GUI
        self.artisan_controller = artisan_controller
        self.calibration_window = None
        self.coord_transformer = CoordinateSystemTransformer()

        self.camera_view = camera_GUI.camera_view
        self.camera_scene = camera_GUI.camera_scene
        self.pixmap_item = camera_GUI.pixmap_item
        self.camera_type = camera_GUI.camera_type

        # track created cross items if you want to clear later
        self._cross_items = []
        self._cross_pos = []

        # Dragging state
        self._dragging_left_mouse = False

        # <<< key line: install an event filter on the viewport >>>
        self.camera_view.viewport().installEventFilter(self)

        # Calibration button
        gui.calibrate_interactive_movement_action.triggered.connect(self.calibrate_coordinate_transformer)

        # Load settings
        self.load_settings()
    
    def load_settings(self):
        if self.artisan_controller and self.camera_type == 'laser_camera':
            tool_head = self.artisan_controller.tool_head
            self.coord_transformer.H_21 = np.array(self.s.get(f"artisan.{tool_head}.camera_H21", None))
        elif self.camera_type == 'overview_camera':
            self.coord_transformer.H_21 = np.array(self.s.get(f"overview_camera.H21", None))
        else:
            print('Camera Type not supported!')

    def eventFilter(self, obj, event):
        try:
            # Only handle mouse presses on this view's viewport
            if obj is not self.camera_view.viewport():
                return False

            # Start dragging on right-button press
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                if event.button() == QtCore.Qt.MouseButton.LeftButton:
                    scene_pt = self.camera_view.mapToScene(event.pos())
                    self._dragging_left_mouse = True
                    self._add_cross(scene_pt)
                    return True
                if event.button() == QtCore.Qt.MouseButton.RightButton and self._cross_items:
                    self._move_to_cross()
                    return True  # eat the event

            # Update cross position while dragging with right button pressed
            if event.type() == QtCore.QEvent.Type.MouseMove and self._dragging_left_mouse:
                #if event.button() == QtCore.Qt.MouseButton.LeftButton:
                if (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
                    scene_pt = self.camera_view.mapToScene(event.pos())
                    self._update_cross(scene_pt)
                    return True

            # Finish dragging on right-button release
            if event.type() == QtCore.QEvent.Type.MouseButtonRelease and self._dragging_left_mouse:
                if event.button() == QtCore.Qt.MouseButton.LeftButton:
                    scene_pt = self.camera_view.mapToScene(event.pos())
                    self._add_cross(scene_pt)
                    self._dragging_left_mouse = False
                    return True

            return False  # let Qt handle other events
            #return super().eventFilter(obj, event)
        except RuntimeError:
            # Widget was deleted
            return False
        
    def _add_cross(self, scene_pt: QtCore.QPoint):
        """Draw a small cross centered at scene_pt, parented to the pixmap so it stays glued to the image."""

        # Remove previous cross items if they exist
        if hasattr(self, '_cross_items'):
            for item in self._cross_items:
                self.camera_scene.removeItem(item)
                self._cross_items = []
            self._cross_pos = []


        local = self.pixmap_item.mapFromScene(scene_pt)
        pm = self.pixmap_item.pixmap()
        if not pm.isNull():
            if not QtCore.QRectF(0, 0, pm.width(), pm.height()).contains(local):
                return        
            
        
        x, y = local.x(), local.y()
        pen = QtGui.QPen(QtGui.QColor(0, 255, 255))
        pen.setWidth(1)
        h_line = QtWidgets.QGraphicsLineItem(0, y, pm.width(), y)
        v_line = QtWidgets.QGraphicsLineItem(x, 0, x, pm.height())
        h_line.setPen(pen)
        v_line.setPen(pen)
        self.camera_scene.addItem(h_line)
        self.camera_scene.addItem(v_line)
        self._cross_items = [h_line, v_line]
        self._cross_pos = [x, y]
    
    def _update_cross(self, scene_pt: QtCore.QPoint):
        """Update the position of the existing cross to a new scene_pt."""
        if not self._cross_items:
            return  # No cross to update
        local = self.pixmap_item.mapFromScene(scene_pt)
        pm = self.pixmap_item.pixmap()
        if not pm.isNull():
            if not QtCore.QRectF(0, 0, pm.width(), pm.height()).contains(local):
                return        
        x, y = local.x(), local.y()
        h_line, v_line = self._cross_items
        h_line.setLine(0, y, pm.width(), y)
        v_line.setLine(x, 0, x, pm.height())
        self._cross_pos = [x, y]
    
    def _move_to_cross(self):
        """Use the artisan controller to move to the position indicated by the cross."""
        if not self._cross_pos:
            return
        x_pix, y_pix = self._cross_pos
        # Transform pixel coordinates to real-world coordinates using the homography
        world_pt = self.coord_transformer.transform_cs2_to_cs1(np.array([[x_pix, y_pix]]))
        if world_pt is None or world_pt.shape[0] == 0:
            print("Failed to transform pixel coordinates to world coordinates.")
            return
        x_world, y_world = world_pt[0]
        try:
            if self.artisan_controller is None:
                return
            self.artisan_controller.move_axis_to(mode="relative", x=x_world, y=y_world, z=0)
            #delete cross after move
            for item in self._cross_items:
                self.camera_scene.removeItem(item)
                self._cross_items = []
            self._cross_pos = []
        except Exception as e:
            print(f"Error moving artisan controller: {e}")
    
    def calibrate_coordinate_transformer(self):
        if self.calibration_window:
            self.calibration_window.close()
        self.calibration_window = TransformerCalibrator(self, self.coord_transformer)
        self.calibration_window.show()


class CoordinateSystemTransformer():
    """
    Estimate and apply a homography between two 2D coordinate systems using point correspondences.
    
    This is useful for mapping points from image pixel coordinates (Coordinate System 2) to
    real-world plane coordinates (Coordinate System 1) and vice versa.
    
    The homography is estimated using the Direct Linear Transform (DLT) algorithm with Hartley
    normalization and optional RANSAC for robustness against outliers.
    """

    def __init__(self):
        self.H_21 = None  # Homography from cs2 to cs1
        
    def _normalize_points(self, pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Hartley normalization: translate to centroid and scale so mean distance = sqrt(2).
        Returns normalized points and the 3x3 normalization matrix T such that x_norm = T @ x.
        """
        if pts.ndim != 2 or pts.shape[1] != 2:
            raise ValueError("pts must be (N,2)")
        c = pts.mean(axis=0)
        shifted = pts - c
        mean_dist = np.sqrt((shifted**2).sum(axis=1)).mean()
        s = np.sqrt(2) / mean_dist if mean_dist > 0 else 1.0
        T = np.array([[s, 0, -s*c[0]],
                    [0, s, -s*c[1]],
                    [0, 0,      1    ]], dtype=float)
        pts_h = np.hstack([pts, np.ones((pts.shape[0],1))])
        pts_norm_h = (T @ pts_h.T).T
        return pts_norm_h[:, :2], T

    def _build_A(self, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
        """
        Build the 2N x 9 DLT system for homography: dst ~ H @ src.
        src, dst are normalized (N,2).
        """
        N = src.shape[0]
        x, y = src[:,0], src[:,1]
        u, v = dst[:,0], dst[:,1]
        zeros = np.zeros(N)
        ones  = np.ones(N)
        A_top = np.stack([ -x, -y, -ones,  zeros, zeros, zeros,  u*x,  u*y,  u], axis=1)
        A_bot = np.stack([ zeros, zeros, zeros,  -x,  -y, -ones,  v*x,  v*y,  v], axis=1)
        A = np.empty((2*N, 9))
        A[0::2] = A_top
        A[1::2] = A_bot
        return A

    def _dlt_homography(self, src_pts: np.ndarray, dst_pts: np.ndarray) -> np.ndarray:
        """
        Compute homography H (3x3) mapping src→dst with DLT and Hartley normalization.
        """
        if src_pts.shape != dst_pts.shape or src_pts.shape[0] < 4:
            raise ValueError("Need at least 4 point pairs with matching shapes (N,2).")
        # Normalize
        src_n, T_src = self._normalize_points(src_pts)
        dst_n, T_dst = self._normalize_points(dst_pts)
        # Build and solve Ah=0
        A = self._build_A(src_n, dst_n)
        _, _, Vt = np.linalg.svd(A)
        h = Vt[-1]
        Hn = h.reshape(3,3)
        # Denormalize: dst ~ T_dst^{-1} * Hn * T_src
        H = np.linalg.inv(T_dst) @ Hn @ T_src
        # Scale so H[2,2] = 1 for consistency
        if np.abs(H[2,2]) > 1e-12:
            H /= H[2,2]
        return H

    def _project(self, H: np.ndarray, pts: np.ndarray) -> np.ndarray:
        """
        Apply homography H to 2D points (N,2). Returns (N,2).
        """
        pts_h = np.hstack([pts, np.ones((pts.shape[0],1))])
        proj = (H @ pts_h.T).T
        proj = proj[:, :2] / proj[:, 2:3]
        return proj

    def _symmetric_transfer_error(self, H: np.ndarray, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
        """
        Symmetric transfer error: ||H*src - dst||^2 + ||H^{-1}*dst - src||^2
        """
        Hinv = np.linalg.inv(H)
        dst_pred = self._project(H, src)
        src_pred = self._project(Hinv, dst)
        return ((dst_pred - dst)**2).sum(axis=1) + ((src_pred - src)**2).sum(axis=1)

    def estimate_homography_cs2_to_cs1(
        self,
        pts_cs2: np.ndarray,
        pts_cs1: np.ndarray,
        use_ransac: bool = True,
        threshold: float = 3.0,
        max_iters: int = 2000,
        confidence: float = 0.99,
        random_state: Optional[int] = None
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, float]]:
        """
        Estimate 3x3 homography H_21 mapping Coordinate System 2 (pixels) → System 1 (world plane).
        
        Parameters
        ----------
        pts_cs2 : (N,2) array
            Points in image/pixel coordinates (x2,y2).
        pts_cs1 : (N,2) array
            Corresponding points in world/plane coordinates (x1,y1).
        use_ransac : bool
            If True, run RANSAC to reject outliers. Otherwise, do a single DLT fit.
        threshold : float
            Inlier threshold on symmetric transfer error (in squared units of coordinates; since both
            domains are in their own units, this is an approximation. If your world units are very
            different from pixels, consider pre-scaling world coords or switch to pure reprojection
            error in the destination space you care about).
        max_iters : int
            Maximum RANSAC iterations.
        confidence : float
            Desired RANSAC success probability (used to adaptively stop).
        random_state : Optional[int]
            RNG seed.

        Returns
        -------
        H_21 : (3,3) array
            Homography mapping cs2 → cs1.
        inliers_mask : (N,) bool array
            True for inlier matches used in the final fit.
        metrics : dict
            {'inlier_ratio', 'rmse_cs1', 'rmse_cs2'} quick diagnostics.
        """
        pts_cs2 = np.asarray(pts_cs2, dtype=float)
        pts_cs1 = np.asarray(pts_cs1, dtype=float)
        if pts_cs2.shape != pts_cs1.shape or pts_cs2.ndim != 2 or pts_cs2.shape[1] != 2:
            raise ValueError("pts_cs2 and pts_cs1 must both be (N,2) with matching shapes.")
        N = pts_cs2.shape[0]
        if N < 4:
            raise ValueError("At least 4 correspondences are required for a homography.")
        # Quick degeneracy check: avoid all (near-)collinear source or destination points
        def _is_degenerate(P):
            # area of convex hull > ~0?
            P0 = P - P.mean(axis=0)
            U, S, _ = np.linalg.svd(P0, full_matrices=False)
            # if smallest singular value is ~0, points are close to collinear
            return S[-1] < 1e-6
        if _is_degenerate(pts_cs2) or _is_degenerate(pts_cs1):
            raise ValueError("Point configuration is (near) degenerate (collinear).")

        rng = np.random.default_rng(random_state)

        if not use_ransac:
            H = self._dlt_homography(pts_cs2, pts_cs1)
            inliers = np.ones(N, dtype=bool)
        else:
            best_inliers = None
            best_H = None
            n_samples = 4  # minimal set for homography
            # Adaptive RANSAC stopping
            it = 0
            best_inlier_ratio = 0.0
            max_allowed_iters = max_iters
            while it < max_allowed_iters:
                # Random minimal sample
                idx = rng.choice(N, size=n_samples, replace=False)
                try:
                    H_candidate = self._dlt_homography(pts_cs2[idx], pts_cs1[idx])
                except Exception:
                    it += 1
                    continue
                errs = self._symmetric_transfer_error(H_candidate, pts_cs2, pts_cs1)
                inliers = errs < threshold**2
                inlier_ratio = inliers.mean()
                if inlier_ratio > best_inlier_ratio and inliers.sum() >= 4:
                    best_inlier_ratio = inlier_ratio
                    best_inliers = inliers
                    # Update required iterations based on inlier ratio
                    # p = inlier_ratio**n_samples chance that a sample is all-inliers
                    p = max(inlier_ratio**n_samples, 1e-12)
                    denom = max(1 - p, 1e-12)
                    max_allowed_iters = min(
                        max_iters,
                        int(np.log(1 - confidence) / np.log(denom)) + 1
                    )
                    # Refit on current inliers for best_H snapshot
                    best_H = self._dlt_homography(pts_cs2[inliers], pts_cs1[inliers])
                it += 1
            if best_inliers is None:
                # Fallback to all data
                best_H = self._dlt_homography(pts_cs2, pts_cs1)
                best_inliers = np.ones(N, dtype=bool)
            H = best_H
            inliers = best_inliers

        # Final refinement on all inliers
        H = self._dlt_homography(pts_cs2[inliers], pts_cs1[inliers])

        # Diagnostics
        pred_cs1 = self._project(H, pts_cs2[inliers])
        rmse_cs1 = np.sqrt(((pred_cs1 - pts_cs1[inliers])**2).sum(axis=1).mean())
        # Also check inverse mapping residual in pixel domain
        invH = np.linalg.inv(H)
        pred_cs2 = self._project(invH, pts_cs1[inliers])
        rmse_cs2 = np.sqrt(((pred_cs2 - pts_cs2[inliers])**2).sum(axis=1).mean())

        metrics = dict(
            inlier_ratio=float(inliers.mean()),
            rmse_cs1=float(rmse_cs1),
            rmse_cs2=float(rmse_cs2),
        )

        self.H_21 = H
        return H, inliers, metrics

    def transform_cs2_to_cs1(self, pts_cs2: np.ndarray) -> np.ndarray:
        """
        Apply H_21 to transform points from Coordinate System 2 (pixels) → System 1 (world).
        """
        if self.H_21 is None:
            return None
        else:
            return self._project(self.H_21, np.asarray(pts_cs2, dtype=float))
        
class TransformerCalibrator(QtWidgets.QWidget):
    def __init__(self, interactive_image_controller:InteractiveImageControl, coord_transformer: CoordinateSystemTransformer):     
        super().__init__()
        widget_path = get_gui_file_path("image_control_calibrator.ui")
        self.point_ui_path = get_gui_file_path("image_control_calibrator_item.ui")
        self.widget_ui=uic.loadUi(str(widget_path), self)
        
        self.coord_transformer = coord_transformer
        self.interactive_image_controller = interactive_image_controller

        self.points_listWidget = self.widget_ui.points_listWidget
        self.widget_ui.add_point_button.clicked.connect(self.add_point)
        self.widget_ui.calc_transform_button.clicked.connect(self.calc_transform)
        self.widget_ui.save_default_button.clicked.connect(self.save_to_default)

    def add_point(self):
        """
        Add a new point to the calibrator and link a GUI element to it
        """
        
        if not self.interactive_image_controller._cross_pos:
            return
        else:
            cross_pos = self.interactive_image_controller._cross_pos

        # put widget it into the list
        point_ui = uic.loadUi(self.point_ui_path)
        item = QtWidgets.QListWidgetItem()
        item.setSizeHint(point_ui.sizeHint())
        self.points_listWidget.addItem(item)
        self.points_listWidget.setItemWidget(item, point_ui)

        point_ui.x_cross_spinbox.setValue(int(cross_pos[0]))
        point_ui.y_cross_spinbox.setValue(int(cross_pos[1]))
        
        def delete_self():
            removed = False
            for i in range(self.points_listWidget.count()):
                item = self.points_listWidget.item(i)
                if self.points_listWidget.itemWidget(item) is point_ui:
                    self.points_listWidget.takeItem(i)
                    removed = True
                    point_ui.deleteLater()
                    break
            return removed
        point_ui.delete_button.clicked.connect(delete_self)
    
    def calc_transform(self):
        """
        Gather all points and compute the homography
        """
        pts_cs2 = []
        pts_cs1 = []
        if self.points_listWidget.count() < 4:
            QtWidgets.QMessageBox.warning(self, "Not enough points", "At least 4 point pairs are required to compute the homography.")
            return
        
        for i in range(self.points_listWidget.count()):
            item = self.points_listWidget.item(i)
            widget = self.points_listWidget.itemWidget(item)
            if widget is not None:
                x_pix = widget.x_cross_spinbox.value()
                y_pix = widget.y_cross_spinbox.value()
                x_world = widget.x_world_spinbox.value()
                y_world = widget.y_world_spinbox.value()
                pts_cs2.append([x_pix, y_pix])
                pts_cs1.append([x_world, y_world])
        pts_cs2 = np.array(pts_cs2, dtype=float)
        pts_cs1 = np.array(pts_cs1, dtype=float)

        try:
            H_21, inliers, metrics = self.coord_transformer.estimate_homography_cs2_to_cs1(
                pts_cs2, pts_cs1, use_ransac=True, threshold=3.0, max_iters=2000, confidence=0.99
            )
            # print("Estimated Homography H_21 (pixel → world):\n", H_21)
            # print("Inliers:", inliers)
            # print("Metrics:", metrics)
            QtWidgets.QMessageBox.information(self, "Calibration successful", f"Homography estimated with {inliers.sum()}/{len(inliers)} inliers.\nRMSE (world): {metrics['rmse_cs1']:.3f}\nRMSE (pixels): {metrics['rmse_cs2']:.3f}")
            #self.close()
            #self.interactive_image_controler.s.set("artisan.laser1064.camera_H21", H_21.tolist())
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Calibration failed", f"Error estimating homography: {e}")
            return
    
    def save_to_default(self):
        """
        Save the current homography to the settings as default
        """
        if self.coord_transformer.H_21 is None:
            QtWidgets.QMessageBox.warning(self, "No homography", "No homography has been computed yet.")
            return
        if self.interactive_image_controller.artisan_controller and self.interactive_image_controller.camera_type == 'laser_camera':
            tool_head = self.interactive_image_controller.artisan_controller.tool_head
            self.interactive_image_controller.s.set(f"artisan.{tool_head}.camera_H21", self.coord_transformer.H_21.tolist())
        elif self.interactive_image_controller.camera_type == 'overview_camera':
            self.interactive_image_controller.s.set(f"overview_camera.H21", self.coord_transformer.H_21.tolist())
        self.interactive_image_controller.s.save_default()
        QtWidgets.QMessageBox.information(self, "Saved", "Current homography saved to settings as default.")




# ----------------------
# # Example usage:

#     # Suppose you have matches: pts in image (cs2) and their corresponding world coords on a plane (cs1).
#     pts_cs2 = np.array([[100, 200], [400, 210], [420, 600], [120, 590], [250, 380]], dtype=float)
#     pts_cs1 = np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 2.0], [0.0, 2.0], [1.5, 1.0]], dtype=float)

#     H_21, inliers, metrics = estimate_homography_cs2_to_cs1(pts_cs2, pts_cs1, use_ransac=True)
#     print("H_21 (pixel → world):\n", H_21)
#     print("Inliers:", inliers)
#     print("Metrics:", metrics)

#     # Transform a new pixel point into world coordinates:
#     new_pixels = np.array([[260, 400], [150, 220]], dtype=float)
#     world_est = transform_cs2_to_cs1(H_21, new_pixels)
#     print("Transformed to world:\n", world_est)