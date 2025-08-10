from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Callable, Optional, Union

from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QFileDialog, QMessageBox,
    QSizePolicy, QLayout
)

# Passe den Import an deinen Modulnamen an
import Settings_Manager as settings_module
SettingsManager = settings_module.SettingsManager

JsonObj = Dict[str, Any]
JsonVal = Union[dict, list, str, int, float, bool, None]


class SettingsEditorWidget(QWidget):
    """
    Lädt ein vorformatiertes UI-Widget (.ui) und befüllt das darin enthaltene
    vertikale Layout 'settings_verticalLayout' dynamisch aus dem Settings-JSON.
    """
    def __init__(self, settings: SettingsManager, ui_path: Path, parent: Optional[QWidget]=None):
        super().__init__(parent)
        self.s = settings
        self._ui_path = Path(ui_path)
        self._updating_from_settings = False
        self._path_setters: Dict[str, Callable[[Any], None]] = {}
        self._path_readers: Dict[str, Callable[[], Any]] = {}

        # --- UI laden ---
        if not self._ui_path.exists():
            raise FileNotFoundError(f"Settings UI file not found: {self._ui_path}")
        # lädt die .ui in diese Instanz, damit Widgets als Attribute verfügbar sind
        uic.loadUi(str(self._ui_path), self)

        # Referenz auf das Ziel-Layout
        obj = getattr(self, "settings_verticalLayout", None)
        if obj is None:
            raise RuntimeError(
                "Im UI fehlt ein Objekt namens 'settings_verticalLayout' (Widget oder Layout)."
            )

        if isinstance(obj, QLayout):
            # Perfekt: wir haben direkt das Layout
            self._target_layout: QVBoxLayout = obj  # type: ignore[assignment]
        elif isinstance(obj, QWidget):
            # Es ist ein Widget – nimm sein Layout oder gib ihm eins
            lay = obj.layout()
            if lay is None:
                lay = QVBoxLayout(obj)
            if not isinstance(lay, QVBoxLayout):
                # wenn's kein VBox ist, geht auch QLayout – wir behandeln es generisch
                pass
            self._target_layout = lay  # type: ignore[assignment]
        else:
            raise RuntimeError(
                f"'settings_verticalLayout' ist ein {type(obj).__name__}, erwarte Widget oder Layout."
            )

        # Buttons (optional) verbinden – passe die Namen bei Bedarf an
        self._connect_button("btnLoadSettings", self._action_load)
        self._connect_button("btnSaveSettings", self._action_save)
        self._connect_button("btnSaveAsSettings", self._action_save_as)

        # initialer Aufbau
        self.rebuild_from_settings()

        # Settings-Events
        self.s.settingChanged.connect(self._on_setting_changed)
        self.s.settingsReplaced.connect(self.rebuild_from_settings)

    # ---------------- Buttons finden & verbinden ----------------
    def _connect_button(self, object_name: str, slot: Callable[[], None]):
        btn = self.findChild(QPushButton, object_name)
        if btn is not None:
            btn.clicked.connect(slot)

    # ---------------- File-Aktionen ----------------
    def _action_load(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Settings laden", "", "JSON (*.json)")
        if not fn:
            return
        try:
            self.s.load_user_file(Path(fn))
            QMessageBox.information(self, "Settings", f"Geladen:\n{fn}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Laden", str(e))

    def _action_save(self):
        last = getattr(self.s, "_last_user_file", None)
        if last is None:
            self._action_save_as()
            return
        try:
            self.s.save_user_file_as(last)
            QMessageBox.information(self, "Settings", f"Gespeichert:\n{last}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", str(e))

    def _action_save_as(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Settings speichern als…", "settings.json", "JSON (*.json)")
        if not fn:
            return
        try:
            self.s.save_user_file_as(Path(fn))
            QMessageBox.information(self, "Settings", f"Gespeichert als:\n{fn}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", str(e))

    # ---------------- Rebuild ----------------
    def rebuild_from_settings(self):
        data = self.s.merged()
        self._clear_layout(self._target_layout)
        self._path_setters.clear()
        self._path_readers.clear()

        if not isinstance(data, dict):
            # defensive: root sollte dict sein
            box = self._make_group_box("Settings", self._target_layout)
            self._add_value_widget("(root)", data, "root", box.layout())
        else:
            for key in sorted(data.keys()):
                val = data[key]
                path = key
                if isinstance(val, dict):
                    self._add_group_for_dict(title=key, d=val, base_path=path, parent_layout=self._target_layout)
                else:
                    # Top-Level-Scalar -> eigene GroupBox mit einer Zeile
                    box = self._make_group_box(key, self._target_layout)
                    self._add_value_widget(key, val, path, box.layout())

        # Stretch am Ende, damit oben nicht gequetscht
        self._target_layout.addStretch(1)

    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ---------------- Builder (rekursiv) ----------------
    def _add_group_for_dict(self, title: str, d: JsonObj, base_path: str, parent_layout: QVBoxLayout):
        box = self._make_group_box(title, parent_layout)
        layout = box.layout()
        for k in sorted(d.keys()):
            v = d[k]
            path = f"{base_path}.{k}"
            self._add_value_widget(k, v, path, layout)

    def _add_value_widget(self, key: str, v: JsonVal, path: str, parent_layout: QVBoxLayout):
        if isinstance(v, dict):
            self._add_group_for_dict(key, v, path, parent_layout)
            return

        if isinstance(v, list):
            if self._list_is_scalar(v):
                self._add_scalar_list_row(key, v, path, parent_layout)
            else:
                row = self._make_row(parent_layout)
                row.addWidget(QLabel(f"{key} (Liste mit Objekten derzeit nicht unterstützt)"))
            return

        # --- Scalar Werte (String/Int/Float/Bool/None) ---
        self._add_scalar_row(key, v, path, parent_layout)

    def _list_is_scalar(self, arr: List[Any]) -> bool:
        if not arr:
            return True
        scalar_types = (str, int, float, bool)
        return all(isinstance(x, scalar_types) or x is None for x in arr)

    # ---------------- Leaf-Renderer ----------------
    def _add_scalar_row(self, key: str, value: Any, path: str, parent_layout: QVBoxLayout):
        row = self._make_row(parent_layout)

        label = QLabel(key)
        label.setMinimumWidth(180)
        row.addWidget(label)

        editor, getter, connect_change = self._make_scalar_editor(value)

        # Settings -> UI
        def apply(val):
            self._updating_from_settings = True
            try:
                self._apply_scalar_value(editor, val)
            finally:
                self._updating_from_settings = False

        self._path_setters[path] = apply

        # UI -> Settings
        connect_change(lambda *_: self._on_ui_scalar_changed(path, getter))

        # Initialwert aus Settings (falls nicht vorhanden, den Default-Wert nutzen)
        apply(self.s.get(path, value))

        row.addStretch(1)

    def _add_scalar_list_row(self, key: str, values: List[Any], path: str, parent_layout: QVBoxLayout):
        row = self._make_row(parent_layout)

        label = QLabel(key)
        label.setMinimumWidth(180)
        row.addWidget(label)

        container = QWidget()
        hl = QHBoxLayout(container)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

        # aktuelle Werte holen
        current_vals = self.s.get(path, values)
        if not isinstance(current_vals, list):
            current_vals = list(values)

        element_editors: List[QWidget] = []
        element_getters: List[Callable[[], Any]] = []
        element_connectors: List[Callable[[Callable], None]] = []

        for val in current_vals:
            ed, get, connect = self._make_scalar_editor(val)
            element_editors.append(ed)
            element_getters.append(get)
            element_connectors.append(connect)
            hl.addWidget(ed)

        def apply_list(new_vals):
            if not isinstance(new_vals, list) or len(new_vals) != len(element_editors):
                # Struktur/Laenge geändert -> kompletter Rebuild
                self.rebuild_from_settings()
                return
            self._updating_from_settings = True
            try:
                for ed, v in zip(element_editors, new_vals):
                    self._apply_scalar_value(ed, v)
            finally:
                self._updating_from_settings = False

        self._path_setters[path] = apply_list

        def on_any_changed(*_):
            if self._updating_from_settings:
                return
            new_list = [g() for g in element_getters]
            self.s.set(path, new_list, layer="user", persist=True)

        for connect in element_connectors:
            connect(on_any_changed)

        apply_list(current_vals)
        row.addWidget(container, 1)
        row.addStretch(0)

    # ---------------- Editor-Fabrik ----------------
    def _make_scalar_editor(self, sample: Any) -> tuple[QWidget, Callable[[], Any], Callable[[Callable], None]]:
        # Bool
        if isinstance(sample, bool):
            w = QCheckBox()
            def getter(): return bool(w.isChecked())
            def connect(cb): w.stateChanged.connect(cb)
            return w, getter, connect

        # Int (nicht-Bool)
        if isinstance(sample, int) and not isinstance(sample, bool):
            w = QSpinBox()
            w.setRange(-2_000_000_000, 2_000_000_000)
            def getter(): return int(w.value())
            def connect(cb): w.valueChanged.connect(cb)
            return w, getter, connect

        # Float
        if isinstance(sample, float):
            w = QDoubleSpinBox()
            w.setRange(-1e12, 1e12)
            w.setDecimals(6)
            w.setSingleStep(0.1)
            def getter(): return float(w.value())
            def connect(cb): w.valueChanged.connect(cb)
            return w, getter, connect

        # String / None -> LineEdit
        w = QLineEdit()
        def getter(): return w.text()
        # „fertig getippt“ reicht oft, andernfalls textEdited für live
        def connect(cb): w.editingFinished.connect(cb)
        return w, getter, connect

    def _apply_scalar_value(self, editor: QWidget, val: Any):
        if isinstance(editor, QCheckBox):
            editor.setChecked(bool(val))
        elif isinstance(editor, QSpinBox):
            try: editor.setValue(int(val))
            except Exception: pass
        elif isinstance(editor, QDoubleSpinBox):
            try: editor.setValue(float(val))
            except Exception: pass
        elif isinstance(editor, QLineEdit):
            editor.setText("" if val is None else str(val))

    # ---------------- Events ----------------
    def _on_ui_scalar_changed(self, path: str, getter: Callable[[], Any]):
        if self._updating_from_settings:
            return
        val = getter()
        self.s.set(path, val, layer="user", persist=True)

    def _on_setting_changed(self, path: str, value: Any):
        apply = self._path_setters.get(path)
        if apply:
            apply(value)

    # ---------------- Helpers ----------------
    def _make_group_box(self, title: str, parent_layout: QVBoxLayout) -> QGroupBox:
        box = QGroupBox(title)
        # Wichtig: nicht „Maximum“, sonst kann Inhalt „verschwinden“
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        parent_layout.addWidget(box)
        return box

    def _make_row(self, parent_layout: QVBoxLayout) -> QHBoxLayout:
        row_container = QWidget()
        row = QHBoxLayout(row_container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        parent_layout.addWidget(row_container)
        return row