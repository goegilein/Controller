"""The app's look: BildHatcher's "Atelier" style, dark or bright (REVISION_PLAN.md P4.2).

Taken over from BildHatcher (theme.py, GUI_Files/styles/atelier.qss, the fonts and the four stylesheet images), so
both programs of the suite look alike. In v3.0 this goes into the shared package. The stylesheet is the source of the
look: a template whose @tokens the two palettes in its header define. This module

  * renders it for a mode ("dark" / "light") and applies it to the whole application,
  * loads the fonts (Plus Jakarta Sans, Space Mono – SIL Open Font License, GUI_files/fonts),
  * registers the "icons:" search path used by url(icons:...) in the stylesheet,
  * gives the palette to the few colours set in code: color(name), and the signal colours of the machine state
    (signal(name)), which stay the same in both modes so a stop button always looks like a stop button.

Unlike BildHatcher the controller's pictograms are coloured PNGs that work on both backgrounds, so a mode switch
only re-applies the stylesheet and tells the code that colours things itself (on_change).
"""
import re

from PyQt6 import QtCore, QtGui, QtWidgets

from PathManager import get_gui_file_path

STYLE = "atelier"
EXTRA = "controller"           # GUI_files/styles/controller.qss: what the controller adds
MODES = ("dark", "light")
STYLE_DIR = get_gui_file_path("styles")
FONT_DIR = get_gui_file_path("fonts")
ICON_DIR = get_gui_file_path("icons")
FONT_TEXT = "Plus Jakarta Sans"
FONT_MONO = "Space Mono"

# machine signals (same in both modes): readable on the dark and the bright background
SIGNALS = {"ok": "#43A047", "warning": "#EF6C00", "error": "#E53935", "stop": "#EF6C00", "estop": "#C62828",
           "onSignal": "#FFFFFF", "idle": "#94A3B8"}

MODE = "dark"
_callbacks = []

QtCore.QDir.addSearchPath("icons", str(ICON_DIR))


def template(name=STYLE):
    return (STYLE_DIR / f"{name}.qss").read_text(encoding="utf-8")


def palettes(name=STYLE):
    """{mode: {token: value}} from the @palette blocks in the stylesheet's header."""
    result = {}
    for mode, body in re.findall(r"@palette\s+(\w+)\s*\n(.*?)@end", template(name), flags=re.S):
        values = {}
        for row in body.splitlines():
            parts = row.split(None, 1)
            if len(parts) == 2:
                value = re.match(r"(rgba?\([^)]*\)|#[0-9A-Fa-f]{3,8})", parts[1].strip())
                if value:
                    values[parts[0]] = value.group(1)
        result[mode] = values
    return result


def render(mode=None, name=STYLE):
    """The stylesheet with the palette of `mode` filled in: atelier.qss + the controller's additions."""
    palette = palettes(name)[mode or MODE]
    text = template(name)
    if name == STYLE and (STYLE_DIR / f"{EXTRA}.qss").exists():
        text += "\n" + template(EXTRA)
    return re.sub(r"@([A-Za-z]+)\b", lambda m: palette.get(m.group(1), m.group(0)), text)


def color(token, mode=None):
    """Colour string of a palette token, e.g. color("muted")."""
    return palettes()[mode or MODE][token]


def signal(name):
    return SIGNALS[name]


_fonts_loaded = []


def load_fonts():
    """Register the bundled fonts (once). Returns the loaded families."""
    if not _fonts_loaded:
        for path in sorted(FONT_DIR.glob("*.ttf")):
            font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                _fonts_loaded.extend(QtGui.QFontDatabase.applicationFontFamilies(font_id))
    return sorted(set(_fonts_loaded))


def on_change(callback):
    """Call `callback()` after every mode switch (code that sets colours itself)."""
    _callbacks.append(callback)
    return callback


def apply(app=None, mode=None):
    """Fonts + stylesheet for the whole application."""
    global MODE
    MODE = mode if mode in MODES else MODE
    app = app or QtWidgets.QApplication.instance()
    load_fonts()
    font = QtGui.QFont(FONT_TEXT)
    font.setPointSizeF(9)
    app.setFont(font)
    app.setStyleSheet(render(MODE))
    return app


# --- pictograms: the controller's PNGs are one-coloured; they are drawn in the mode's text colour ---
def tint_icon(icon, colour=None):
    """`icon` with every visible pixel in `colour` (default: the palette's text colour)."""
    sizes = icon.availableSizes()
    size = max(sizes, key=lambda s: s.width()) if sizes else QtCore.QSize(64, 64)
    image = icon.pixmap(size).toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    painter = QtGui.QPainter(image)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), QtGui.QColor(colour or color("text")))
    painter.end()
    return QtGui.QIcon(QtGui.QPixmap.fromImage(image))


def set_icon(button, icon):
    """Give `button` the pictogram `icon` (QIcon or a file name in GUI_files/resources), tinted for the mode."""
    if not isinstance(icon, QtGui.QIcon):
        from PathManager import get_resource_path
        icon = QtGui.QIcon(str(get_resource_path(icon)))
    button.setProperty("themeIcon", icon)   # the original, so a mode switch tints from it again
    button.setIcon(tint_icon(icon))


def tint_buttons(root):
    """Tint the pictograms of every button under `root` (the originals are kept in the "themeIcon" property)."""
    buttons = root.findChildren(QtWidgets.QAbstractButton)
    if isinstance(root, QtWidgets.QAbstractButton):
        buttons.append(root)
    for button in buttons:
        source = button.property("themeIcon")
        if source is None:
            if button.icon().isNull():
                continue
            source = button.icon()
            button.setProperty("themeIcon", source)
        button.setIcon(tint_icon(source))
    return root


def load_ui(path, base=None):
    """uic.loadUi + pictograms in the mode's colour – use it for every .ui file."""
    from PyQt6 import uic
    widget = uic.loadUi(str(path), base) if base is not None else uic.loadUi(str(path))
    return tint_buttons(widget)


def set_mode(mode, window=None):
    """Switch dark / light at run time (`window` is accepted for BildHatcher's signature)."""
    if mode not in MODES:
        raise ValueError(mode)
    apply(mode=mode)
    for top in QtWidgets.QApplication.topLevelWidgets():
        tint_buttons(top)
    for callback in list(_callbacks):
        try:
            callback()
        except RuntimeError:  # a widget of a closed window
            _callbacks.remove(callback)
