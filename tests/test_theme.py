"""P4.2: BildHatcher's Atelier style in the controller – stylesheet, fonts, tinted pictograms, dark / bright switch."""
import re

from PyQt6 import QtCore, QtGui, QtWidgets

import theme
from PathManager import get_gui_file_path
from test_bridge import qapp  # noqa: F401  (fixture)


def test_both_palettes_fill_every_token():
    rules = re.sub(r"/\*.*?\*/", "", theme.template() + theme.template(theme.EXTRA), flags=re.S)
    tokens = set(re.findall(r"@([A-Za-z]+)", rules))
    for mode in theme.MODES:
        assert tokens <= set(theme.palettes()[mode]), (mode, tokens - set(theme.palettes()[mode]))
        assert "@" not in re.sub(r"/\*.*?\*/", "", theme.render(mode), flags=re.S)


def test_no_ui_file_carries_its_own_stylesheet():
    """The look comes from the theme only (v1.0's burgundy is kept in styles/legacy_burgundy.qss)."""
    for path in get_gui_file_path("").glob("*.ui"):
        assert 'name="styleSheet"' not in path.read_text(encoding="utf-8"), path.name
    assert "rgb(122, 0, 28)" in get_gui_file_path("styles/legacy_burgundy.qss").read_text(encoding="utf-8")


def test_apply_loads_fonts_and_the_stylesheet_images(qapp):
    theme.apply(qapp, "dark")
    assert {"Plus Jakarta Sans", "Space Mono"} <= set(theme.load_fonts())
    assert qapp.styleSheet() == theme.render("dark")
    for name in ("spin-up", "spin-down", "combo-down", "check"):
        assert QtCore.QFile.exists(f"icons:{name}.svg"), name


def colour_of(button):
    image = button.icon().pixmap(32, 32).toImage()
    return next(image.pixelColor(x, y) for y in range(32) for x in range(32) if image.pixelColor(x, y).alpha() == 255)


def same(a, token, mode):
    b = QtGui.QColor(theme.color(token, mode))
    return all(abs(x - y) <= 2 for x, y in zip(a.getRgb()[:3], b.getRgb()[:3]))


def test_pictograms_follow_the_mode(qapp):
    theme.apply(qapp, "dark")
    widget = theme.load_ui(get_gui_file_path("Controller.ui"))
    home = next(b for b in widget.findChildren(QtWidgets.QAbstractButton)
                if b.property("themeIcon") is not None and "home" in b.objectName().lower())
    assert same(colour_of(home), "text", "dark")
    theme.set_mode("light")
    assert same(colour_of(home), "text", "light")   # dark on bright
    button = QtWidgets.QPushButton()
    theme.set_icon(button, "pause.png")                                                  # black PNG
    assert same(colour_of(button), "text", "light")
    theme.set_mode("dark")
    assert same(colour_of(button), "text", "dark")
    widget.close()


def test_bright_mode_button_switches_and_is_remembered(qapp):
    from test_bridge import Setup
    from machine_safety_ui import MachineBar

    class Settings:
        values = {}

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

    theme.apply(qapp, "dark")
    window = QtWidgets.QMainWindow()
    s = Setup()
    settings = Settings()
    bar = MachineBar(window, s.ac, confirm_fn=lambda *a: False, settings=settings)
    bar.theme_button.click()
    assert theme.MODE == "light" and settings.values == {"ui.theme": "light"}
    assert qapp.styleSheet() == theme.render("light")
    bar.theme_button.click()
    assert theme.MODE == "dark" and settings.values == {"ui.theme": "dark"}
    s.close()
    window.close()
