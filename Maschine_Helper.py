# points_circle_controller.py
from __future__ import annotations
import math
import numpy as np


from PyQt6.QtWidgets import (
    QWidget, QListWidget, QListWidgetItem, QHBoxLayout, QPushButton,
    QDoubleSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal, QObject


class PointItemWidget(QWidget):
    """One row: [X spin] [Y spin] [Z spin] [Update position] [Delete]"""
    valueChanged = Signal(int, float, float, float)   # row_index, x, y, z
    requestDelete = Signal(int)                      # row_index
    requestUpdateFromCurrent = Signal(int)           # row_index

    def __init__(self, row_index: int, x=0.0, y=0.0, z=0.0, parent=None):
        super().__init__(parent)
        self.row_index = row_index

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)

        self.sx = QDoubleSpinBox()
        self.sy = QDoubleSpinBox()
        self.sz = QDoubleSpinBox()
        for sp in (self.sx, self.sy, self.sz):
            sp.setDecimals(6)
            sp.setRange(-1e9, 1e9)
            sp.setSingleStep(0.1)
            sp.setKeyboardTracking(False)  # only emit on commit

        self.sx.setValue(x); self.sy.setValue(y); self.sz.setValue(z)

        self.btnUpdate = QPushButton("Update position")
        self.btnDelete = QPushButton("Delete")

        lay.addWidget(self.sx)
        lay.addWidget(self.sy)
        lay.addWidget(self.sz)
        lay.addWidget(self.btnUpdate)
        lay.addWidget(self.btnDelete)

        # Wire up signals
        for sp in (self.sx, self.sy, self.sz):
            sp.valueChanged.connect(self._on_spin_change)

        self.btnDelete.clicked.connect(lambda: self.requestDelete.emit(self.row_index))
        self.btnUpdate.clicked.connect(lambda: self.requestUpdateFromCurrent.emit(self.row_index))

    def _on_spin_change(self, _):
        self.valueChanged.emit(self.row_index, self.sx.value(), self.sy.value(), self.sz.value())

    def set_row_index(self, idx: int):
        self.row_index = idx

    def set_values(self, x, y, z):
        # block signals during programmatic set
        for sp, v in ((self.sx, x), (self.sy, y), (self.sz, z)):
            old = sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(old)
        # after set, emit one consolidated change
        self.valueChanged.emit(self.row_index, self.sx.value(), self.sy.value(), self.sz.value())

    def get_values(self):
        return (self.sx.value(), self.sy.value(), self.sz.value())


class AddButtonWidget(QWidget):
    """The special last-row widget containing only the 'Add current position' button."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self.btn = QPushButton("➕ Add current position")
        self.btn.clicked.connect(self.clicked.emit)
        lay.addWidget(self.btn)


class PointsCircleController(QObject):
    """
    Attaches to an existing QListWidget and manages:
      - persistent list of points (self.points: list[tuple[float,float,float]])
      - always-last 'Add current position' row
      - recompute center on any change
    """
    centerChanged = Signal(object)  # None or (cx, cy, cz)

    def __init__(
        self,
        list_widget: QListWidget,
        get_current_position,                  # callable -> (x, y, z)
        on_center_changed=None                 # optional callback(center)
    ):
        super().__init__(list_widget)
        self.list_widget = list_widget
        self.get_current_position = get_current_position
        self.points: list[tuple[float, float, float]] = []
        self._add_item = None  # (QListWidgetItem, AddButtonWidget)

        if on_center_changed:
            self.centerChanged.connect(on_center_changed)

        # Prepare the list: clear and insert the add button row
        self.list_widget.clear()
        self._insert_add_button_row()

        # Ensure selection doesn't get weird on the button row
        self.list_widget.setSelectionMode(self.list_widget.SingleSelection)

        # Initial compute
        self._emit_center()

    # ---------- Public API ----------
    def add_point_from_current(self):
        try:
            x, y, z = self.get_current_position()
        except Exception as e:
            QMessageBox.warning(self.list_widget, "Error", f"Couldn't get current position:\n{e}")
            return
        self._add_point_row(float(x), float(y), float(z))
        self._emit_center()

    def get_points(self):
        return list(self.points)

    # ---------- Internal: UI rows management ----------
    def _insert_add_button_row(self):
        # Create the last row with 'Add current position'
        add_item = QListWidgetItem()
        add_widget = AddButtonWidget()
        add_widget.clicked.connect(self.add_point_from_current)

        # Insert at end
        self.list_widget.addItem(add_item)
        self.list_widget.setItemWidget(add_item, add_widget)
        add_item.setFlags(Qt.ItemIsEnabled)  # not selectable/editable
        self._add_item = (add_item, add_widget)

    def _ensure_add_button_is_last(self):
        # If anything moved, re-append the add button item to the end
        if not self._add_item:
            self._insert_add_button_row()
            return
        add_item, add_widget = self._add_item
        idx = self.list_widget.row(add_item)
        if idx != self.list_widget.count() - 1:
            # remove and append again
            self.list_widget.takeItem(idx)
            self.list_widget.addItem(add_item)
            self.list_widget.setItemWidget(add_item, add_widget)

    def _add_point_row(self, x, y, z):
        # Insert before the add button row
        insert_idx = self.list_widget.count() - 1  # spot before the last
        item = QListWidgetItem()
        w = PointItemWidget(len(self.points), x, y, z)
        w.valueChanged.connect(self._on_point_edited)
        w.requestDelete.connect(self._on_point_delete)
        w.requestUpdateFromCurrent.connect(self._on_point_update_from_current)

        self.list_widget.insertItem(insert_idx, item)
        self.list_widget.setItemWidget(item, w)

        # Update internal list
        self.points.append((x, y, z))

        self._renumber_rows()
        self._ensure_add_button_is_last()

    def _on_point_delete(self, row_index: int):
        # Remove the visual row
        # The row_index maps to current index among point rows (0..len(points)-1)
        item_idx = row_index  # because add-button is last, indices align
        item = self.list_widget.takeItem(item_idx)
        del item  # allow GC

        # Remove from model
        if 0 <= row_index < len(self.points):
            del self.points[row_index]

        self._renumber_rows()
        self._ensure_add_button_is_last()
        self._emit_center()

    def _on_point_update_from_current(self, row_index: int):
        try:
            x, y, z = self.get_current_position()
        except Exception as e:
            QMessageBox.warning(self.list_widget, "Error", f"Couldn't get current position:\n{e}")
            return

        # Update both UI and model
        widget = self._row_widget(row_index)
        if widget:
            widget.set_values(x, y, z)  # emits valueChanged -> updates model & recompute

    def _on_point_edited(self, row_index: int, x: float, y: float, z: float):
        if 0 <= row_index < len(self.points):
            self.points[row_index] = (float(x), float(y), float(z))
        self._emit_center()

    def _row_widget(self, point_row_index: int) -> PointItemWidget | None:
        if not (0 <= point_row_index < self.list_widget.count() - 1):
            return None
        item = self.list_widget.item(point_row_index)
        w = self.list_widget.itemWidget(item)
        return w

    def _renumber_rows(self):
        # Keep row indices in sync inside the row widgets
        for i in range(self.list_widget.count() - 1):  # exclude last "add" row
            w = self._row_widget(i)
            if isinstance(w, PointItemWidget):
                w.set_row_index(i)

    # ---------- Center computation orchestration ----------
    def _emit_center(self):
        center = compute_circle_center_or_mean(self.points)
        self.centerChanged.emit(center)


# ---------- Geometry helpers ----------

def compute_circle_center_or_mean(points: list[tuple[float, float, float]]):
    """
    Returns:
      - None if no points
      - mean (x,y,z) if < 3 points
      - best-fit 3D circle center (x,y,z) if >= 3 points
    """
    n = len(points)
    if n == 0:
        return None
    if n < 3:
        # simple mean
        arr = np.array(points, dtype=float)
        return tuple(arr.mean(axis=0))

    pts = np.array(points, dtype=float)  # (n,3)

    # Step 1: fit plane via PCA
    centroid = pts.mean(axis=0)
    X = pts - centroid
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
    c2d, r = fit_circle_2d_kasa(proj2d)
    if c2d is None or not np.isfinite(c2d).all():
        # fallback to mean if numeric issues
        return tuple(centroid.tolist())

    # Step 5: lift center back to 3D: centroid + c2d_x * u + c2d_y * v
    center3d = centroid + c2d[0] * u + c2d[1] * v
    return tuple(center3d.tolist())


def fit_circle_2d_kasa(pts2: np.ndarray):
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
        r = math.sqrt(max(a * a + b0 * b0 + c, 0.0))
        return np.array([a, b0]), r
    except np.linalg.LinAlgError:
        return None, None
