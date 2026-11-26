"""Settings dialog: settings with a fixed set of values are drop-downs (rotary_motors.control_mode, ui.theme, ...)."""
from PyQt6 import QtWidgets

from conftest import FIXTURES
from PathManager import get_gui_file_path
from Settings_Binder import CHOICES, SettingsEditorWidget
from Settings_Manager import SettingsManager
from test_bridge import qapp  # noqa: F401  (fixture)


def combo_for(widget, path):
    """The drop-down in the row whose label is the last part of `path`, inside the group of its first part."""
    group = next(g for g in widget.findChildren(QtWidgets.QGroupBox) if g.title() == path.split(".")[0])
    label = next(lab for lab in group.findChildren(QtWidgets.QLabel) if lab.text() == path.split(".")[-1])
    return label.parentWidget().findChild(QtWidgets.QComboBox)


def test_control_mode_is_a_drop_down_with_the_allowed_values(qapp):
    settings = SettingsManager(default_settings_path=FIXTURES / "settings.json")
    widget = SettingsEditorWidget(settings, get_gui_file_path("Settings_widget.ui"))
    combo = combo_for(widget, "rotary_motors.control_mode")
    assert [combo.itemText(i) for i in range(combo.count())] == CHOICES["rotary_motors.control_mode"]
    assert combo.currentText() == "wheel"
    combo.setCurrentText("position")
    assert settings.get("rotary_motors.control_mode") == "position"
    settings.set("rotary_motors.control_mode", "wheel")                       # and back: settings -> dialog
    assert combo.currentText() == "wheel"
    assert combo_for(widget, "ui.theme") is not None and combo_for(widget, "rotary_motors.series") is not None
    widget.close()
