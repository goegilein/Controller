"""Machine bar (REVISION_PLAN.md P2.8c): machine state, software Stop and E-stop, error acknowledge.

Both stops ask for confirmation (C2: the Artisan has a hardware E-stop; the software ones are secured by a question).
Enter confirms – the confirm button is the default. Hotkeys work in the whole application:
    F9  = Stop     (quick stop M410, laser off; the head stays where it is)
    F12 = E-stop   (M112: the firmware halts; restart the machine, then reconnect and home)
"""
from PyQt6 import QtCore, QtGui, QtWidgets

import theme

STOP_KEY = "F9"
ESTOP_KEY = "F12"

STATE_STYLE = {  # text, colour: a theme signal, or "accent" (the palette's gold) for activity
    "disconnected": ("Disconnected", "idle"),
    "connecting": ("Connecting…", "idle"),
    "idle": ("Idle", "ok"),
    "busy": ("Busy", "accent"),
    "running": ("Running", "accent"),
    "paused": ("Paused", "warning"),
    "error": ("ERROR – acknowledge", "error"),
    "estop": ("E-STOP – restart machine, reconnect", "error"),
}


def _signal_button(button, signal):
    """Stop / E-stop keep their signal colour in both modes (the theme's buttons are neutral)."""
    button.setStyleSheet(f"QPushButton {{ background:{theme.signal(signal)}; color:{theme.signal('onSignal')}; "
                         "font-weight:bold; padding:6px 18px; border:none; border-radius:6px; }"
                         "QPushButton:disabled { background:rgba(127,127,127,0.25); color:rgba(127,127,127,0.8); }")


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
    def __init__(self, window: QtWidgets.QMainWindow, artisan, confirm_fn=confirm, settings=None):
        super().__init__("Machine", window)
        self.ac = artisan
        self.settings = settings
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

        # P4.2: bright / dark look (remembered in the settings as ui.theme)
        self.theme_button = QtWidgets.QPushButton("Bright mode")
        self.theme_button.setCheckable(True)
        self.theme_button.setChecked(theme.MODE == "light")
        self.theme_button.toggled.connect(self.set_bright)
        if settings is not None and hasattr(settings, "settingChanged"):
            settings.settingChanged.connect(self._on_setting)      # e.g. ui.theme chosen in the settings dialog
        self.addWidget(self.theme_button)
        self.addSeparator()

        self.stop_button = QtWidgets.QPushButton(f"STOP  ({STOP_KEY})")
        _signal_button(self.stop_button, "stop")
        self.stop_button.clicked.connect(self.request_stop)
        self.addWidget(self.stop_button)

        self.estop_button = QtWidgets.QPushButton(f"EMERGENCY STOP  ({ESTOP_KEY})")
        _signal_button(self.estop_button, "estop")
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
        theme.on_change(lambda: self.on_state(self.ac.state, ""))

    def on_state(self, state, reason):
        text, signal = STATE_STYLE.get(state, (state, "idle"))
        color = theme.color("accentText") if signal == "accent" else theme.signal(signal)
        self.state_label.setText(f"Machine: {text}")
        self.state_label.setStyleSheet(f"color:{color}; font-weight:bold;")
        connected = state not in ("disconnected", "connecting", "estop")
        self.stop_button.setEnabled(connected)
        self.estop_button.setEnabled(connected)
        self.ack_button.setEnabled(state == "error")
        if reason:
            self.status_bar.showMessage(f"{text}: {reason}", 10000)

    def set_bright(self, bright):
        mode = "light" if bright else "dark"
        if mode != theme.MODE:
            theme.set_mode(mode, self.window())
        if self.settings is not None and self.settings.get("ui.theme") != mode:
            self.settings.set("ui.theme", mode)

    def _on_setting(self, path, value):
        if path == "ui.theme" and value in theme.MODES and value != theme.MODE:
            self.theme_button.setChecked(value == "light")     # switches through set_bright

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
