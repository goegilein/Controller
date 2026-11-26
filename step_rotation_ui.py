"""Part rotation of a process step (REVISION_PLAN.md P2.6): button in the step widget and its dialog.

The button shows the rotation the job uses ("Rot 12.30°"). A click opens the dialog with the measured 3×3 matrix,
Rz and the tilt, and lets the user take position + rotation from a stored position or reset the rotation.
Only Rz goes into the job; a tilt above TILT_WARNING_DEG is shown as a warning (decision 2026-11-24).
"""
import numpy as np
from PyQt6 import QtWidgets

from job_bridge import TILT_WARNING_DEG
import theme
from machine_core.job import rz_deg, tilt_deg


def rotation_text(step):
    rotation = getattr(step, "rotation", None)
    if rotation is None:
        return "Rot\n0.00°"
    text = f"Rot\n{rz_deg(rotation):.2f}°"
    return text + "\n⚠ tilt" if tilt_deg(rotation) > TILT_WARNING_DEG else text


class StepRotationDialog(QtWidgets.QDialog):
    def __init__(self, handler, step, stored_points=None, parent=None):
        super().__init__(parent)
        self.handler = handler
        self.step = step
        self.stored_points = stored_points
        self.setWindowTitle(f"Part rotation – {step.name}")
        layout = QtWidgets.QVBoxLayout(self)

        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.matrix = QtWidgets.QTableWidget(3, 3)
        self.matrix.setHorizontalHeaderLabels(["X", "Y", "Z"])
        self.matrix.setVerticalHeaderLabels(["X", "Y", "Z"])
        self.matrix.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix.setFixedHeight(120)
        layout.addWidget(self.matrix)

        row = QtWidgets.QHBoxLayout()
        self.points = QtWidgets.QComboBox()
        self.apply_button = QtWidgets.QPushButton("Apply position + rotation")
        self.apply_button.clicked.connect(self.apply_stored_point)
        row.addWidget(QtWidgets.QLabel("Stored position:"))
        row.addWidget(self.points, 1)
        row.addWidget(self.apply_button)
        layout.addLayout(row)

        buttons = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton("Reset rotation")
        self.reset_button.clicked.connect(self.reset)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.fill_points()
        self.refresh()

    def fill_points(self):
        self.points.clear()
        for point in getattr(self.stored_points, "points", None) or []:
            rotation = getattr(point, "rotation", None)
            extra = "no rotation" if rotation is None else f"Rz {rz_deg(rotation):.2f}°, tilt {tilt_deg(rotation):.2f}°"
            self.points.addItem(f"{point.name}  ({extra})", point)
        self.apply_button.setEnabled(self.points.count() > 0)

    def refresh(self):
        rotation = getattr(self.step, "rotation", None)
        r = np.eye(3) if rotation is None else np.asarray(rotation, float)
        for i in range(3):
            for j in range(3):
                self.matrix.setItem(i, j, QtWidgets.QTableWidgetItem(f"{r[i, j]:+.5f}"))
        if rotation is None:
            self.info.setText("Not rotated – the job runs axis-parallel to the machine.")
            self.info.setStyleSheet("")
            return
        rz, tilt = rz_deg(r), tilt_deg(r)
        source = getattr(self.step, "rotation_source", None)
        text = (f"Measured rotation{f' from {source}' if source else ''}.\n"
                f"The job uses the rotation about Z: Rz = {rz:.3f}°.\nTilt (not applied): {tilt:.3f}°")
        if tilt > TILT_WARNING_DEG:
            text += f"\n⚠ Tilt above {TILT_WARNING_DEG}°: the holder is not level, the job stays flat."
            self.info.setStyleSheet(f"color:{theme.signal('warning')}; font-weight:bold;")
        else:
            self.info.setStyleSheet("")
        self.info.setText(text)

    def apply_stored_point(self):
        point = self.points.currentData()
        if point is not None and self.handler.set_step_from_stored_point(self.step, point):
            self.refresh()

    def reset(self):
        if self.handler.reset_step_rotation(self.step):
            self.refresh()


def add_rotation_button(process_ui, step, widget):
    """Adds the rotation button to a step widget (column 5 of its position grid); returns the button."""
    button = QtWidgets.QPushButton(rotation_text(step))
    button.setObjectName("rotation_button")
    button.setToolTip("Part rotation of this step (click for the matrix, Rz and tilt)")

    def open_dialog():
        dialog = StepRotationDialog(process_ui.process_handler, step, getattr(process_ui, "stored_points", None), widget)
        dialog.exec()
        button.setText(rotation_text(step))
        process_ui.refresh_step_widget(step, widget)

    button.clicked.connect(open_dialog)
    widget.gridLayout_4.addWidget(button, 0, 5, 4, 1)
    widget.rotation_dialog_factory = lambda: StepRotationDialog(
        process_ui.process_handler, step, getattr(process_ui, "stored_points", None), widget)
    return button
