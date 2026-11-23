"""Machine bar (REVISION_PLAN.md P2.8c): machine state, software Stop and E-stop, error acknowledge.

Both stops ask for confirmation (C2: the Artisan has a hardware E-stop; the software ones are secured by a question).
Enter confirms – the confirm button is the default. Hotkeys work in the whole application:
    F9  = Stop     (quick stop M410, laser off; the head stays where it is)
    F12 = E-stop   (M112: the firmware halts; restart the machine, then reconnect and home)
"""
from PyQt6 import QtCore, QtGui, QtWidgets

STOP_KEY = "F9"
ESTOP_KEY = "F12"

STATE_STYLE = {
    "disconnected": ("Disconnected", "#888888"),
    "connecting": ("Connecting…", "#888888"),
    "idle": ("Idle", "#2e7d32"),
    "busy": ("Busy", "#1565c0"),
    "running": ("Running", "#1565c0"),
    "paused": ("Paused", "#ef6c00"),
    "error": ("ERROR – acknowledge", "#c62828"),
    "estop": ("E-STOP – restart machine, reconnect", "#c62828"),
}


def confirm(parent, title, text, confirm_text):
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(confirm_text, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes)  # Enter confirms
    box.exec()
    return box.clickedButton() is yes


class MachineBar(QtWidgets.QToolBar):
    def __init__(self, window: QtWidgets.QMainWindow, artisan, confirm_fn=confirm):
        super().__init__("Machine", window)
        self.ac = artisan
        self.confirm = confirm_fn
        self.setObjectName("machine_bar")
        self.setMovable(False)

        self.state_label = QtWidgets.QLabel()
        self.state_label.setMinimumWidth(260)
        self.addWidget(self.state_label)
        self.addSeparator()

        self.ack_button = QtWidgets.QPushButton("Acknowledge error")
        self.ack_button.clicked.connect(self.ac.acknowledge_error)
        self.addWidget(self.ack_button)

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        self.stop_button = QtWidgets.QPushButton(f"STOP  ({STOP_KEY})")
        self.stop_button.setStyleSheet("background:#ef6c00; color:white; font-weight:bold; padding:6px 18px;")
        self.stop_button.clicked.connect(self.request_stop)
        self.addWidget(self.stop_button)

        self.estop_button = QtWidgets.QPushButton(f"EMERGENCY STOP  ({ESTOP_KEY})")
        self.estop_button.setStyleSheet("background:#c62828; color:white; font-weight:bold; padding:6px 18px;")
        self.estop_button.clicked.connect(self.request_estop)
        self.addWidget(self.estop_button)

        for key, slot in ((STOP_KEY, self.request_stop), (ESTOP_KEY, self.request_estop)):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), window)
            shortcut.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)

        self.status_bar = window.statusBar()
        self.ac.state_callbacks.append(self.on_state)
        self.ac.error_callbacks.append(self.on_error)
        window.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self)
        self.on_state(self.ac.state, "")

    def on_state(self, state, reason):
        text, color = STATE_STYLE.get(state, (state, "#888888"))
        self.state_label.setText(f"Machine: {text}")
        self.state_label.setStyleSheet(f"color:{color}; font-weight:bold;")
        connected = state not in ("disconnected", "connecting", "estop")
        self.stop_button.setEnabled(connected)
        self.estop_button.setEnabled(connected)
        self.ack_button.setEnabled(state == "error")
        if reason:
            self.status_bar.showMessage(f"{text}: {reason}", 10000)

    def on_error(self, message):
        self.status_bar.showMessage(f"ERROR: {message}")

    def request_stop(self):
        if not self.stop_button.isEnabled():
            return
        if self.confirm(self.window(), "Stop",
                        "Stop the machine now?\n\nQuick stop, laser off. The head stays where it is.", "Stop"):
            self.ac.stop()

    def request_estop(self):
        if not self.estop_button.isEnabled():
            return
        if self.confirm(self.window(), "Emergency stop",
                        "EMERGENCY STOP (M112)?\n\nThe firmware halts. Afterwards restart the machine, reconnect and "
                        "home.\nThe hardware emergency stop button always works without this question.",
                        "EMERGENCY STOP"):
            self.ac.emergency_stop()
