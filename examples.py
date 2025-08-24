# main.py
from __future__ import annotations
import sys, json
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox
)
from PyQt6.QtCore import QSettings

from Settings_Manager import SettingsManager
# optional: dein Binder, falls du ihn nutzt
# from settings_binder import SettingsBinder

# ------------------------------------------------------------
# Hilfen: Pfade & optionale Schema-Validierung
# ------------------------------------------------------------
APP_ORG = "MyCompany"
APP_NAME = "LaserApp"

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_DIR = BASE_DIR / "settings"
DEFAULT_SETTINGS_PATH = SETTINGS_DIR / "Default_Settings.json"
SCHEMA_PATH = SETTINGS_DIR / "schema.json"   # optional

def make_schema_validator_or_none():
    """Gibt eine Validator-Funktion zurück, wenn jsonschema vorhanden ist, sonst None."""
    try:
        import jsonschema
    except ImportError:
        return None
    if not SCHEMA_PATH.exists():
        return None
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    def _validator(data: dict):
        jsonschema.validate(instance=data, schema=schema)
    return _validator

def create_settings_manager() -> SettingsManager:
    validator = make_schema_validator_or_none()
    sm = SettingsManager(default_settings_path=DEFAULT_SETTINGS_PATH, schema_validator=validator)
    return sm

# ------------------------------------------------------------
# Deine MainWindow-Klasse
# ------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.settings_qt = QSettings(APP_ORG, APP_NAME)

        # 1) SettingsManager erstellen
        self.sm = create_settings_manager()

        # 2) Zuletzt verwendete User-Settings laden (falls vorhanden)
        last_path_str = self.settings_qt.value("last_settings_path", "", type=str)
        if last_path_str:
            p = Path(last_path_str)
            try:
                if p.exists():
                    self.sm.load_user_file(p)
                    self._update_window_title(p)
            except Exception as e:
                QMessageBox.warning(self, "Settings laden", f"Konnte {p} nicht laden:\n{e}")

        # 3) (Optional) Controller erzeugen und Settings injizieren
        # self.camera = CameraController(self.sm)
        # self.axis   = AxisController(self.sm)
        # self.laser  = LaserController(self.sm)

        # 4) UI aufbauen (Designer-UI oder manuell) und Widgets binden
        self._build_menu()
        # Beispiel: wenn du Widgets hast, kannst du sie binden:
        # self.b_exposure = SettingsBinder(self.sm, self.ui.exposureSpin,
        #                                  "camera.exposure_ms",
        #                                  to_widget=float,
        #                                  from_widget=lambda w: float(w.value()),
        #                                  signal_name="valueChanged")

        # 5) Reaktionen auf Settings-Ereignisse
        self.sm.settingsReplaced.connect(self._on_settings_replaced)

    # --------------------------------------------------------
    # Menü/Aktionen
    # --------------------------------------------------------
    def _build_menu(self):
        m = self.menuBar().addMenu("&Settings")

        act_load = m.addAction("Load…")
        act_load.triggered.connect(self.action_load)

        act_save = m.addAction("Save")
        act_save.triggered.connect(self.action_save)

        act_save_as = m.addAction("Save As…")
        act_save_as.triggered.connect(self.action_save_as)

        m.addSeparator()
        act_export = m.addAction("Export Full (merged)…")
        act_export.triggered.connect(self.action_export_full)

    # ---------------- Actions ----------------
    def action_load(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Load Settings", str(BASE_DIR), "JSON (*.json)"
        )
        if not fn:
            return
        try:
            p = Path(fn)
            self.sm.load_user_file(p)  # validiert & ersetzt User-Layer
            self.settings_qt.setValue("last_settings_path", str(p))
            self._update_window_title(p)
            QMessageBox.information(self, "Settings", "Settings erfolgreich geladen.")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Laden", str(e))

    def action_save(self):
        # Wenn bereits eine User-Datei zugewiesen ist, speichern; sonst Save As…
        if getattr(self.sm, "_last_user_file", None):
            try:
                self.sm.save_user_file_as(self.sm._last_active_file)
                QMessageBox.information(self, "Settings", "Settings gespeichert.")
            except Exception as e:
                QMessageBox.critical(self, "Fehler beim Speichern", str(e))
        else:
            self.action_save_as()

    def action_save_as(self):
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save Settings As", str(BASE_DIR / "user_settings.json"), "JSON (*.json)"
        )
        if not fn:
            return
        try:
            p = Path(fn)
            self.sm.save_user_file_as(p)
            self.settings_qt.setValue("last_settings_path", str(p))
            self._update_window_title(p)
            QMessageBox.information(self, "Settings", f"Gespeichert unter:\n{p}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", str(e))

    def action_export_full(self):
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export Full (merged)", str(BASE_DIR / "full_settings.json"), "JSON (*.json)"
        )
        if not fn:
            return
        try:
            p = Path(fn)
            self.sm.export_full_merged(p)
            QMessageBox.information(self, "Export", f"Vollständige Settings exportiert:\n{p}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Export", str(e))

    # --------------------------------------------------------
    # Reaktion auf kompletten Settings-Austausch (Load)
    # --------------------------------------------------------
    def _on_settings_replaced(self):
        # Falls Controller existieren, deren Parameter neu anwenden:
        # self.camera.reload_from_settings()
        # self.axis.reload_from_settings()
        # self.laser.reload_from_settings()

        # Falls du keinen Binder nutzt: Widgets manuell aus Settings füllen:
        # self.ui.exposureSpin.setValue(float(self.sm.get("camera.exposure_ms", 10.0)))
        pass

    def _update_window_title(self, path: Path | None):
        name = path.name if path else "untitled"
        self.setWindowTitle(f"{APP_NAME} — {name}")

# ------------------------------------------------------------
# App-Start
# ------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    # QSettings konfigurieren
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)

    # Sicherstellen, dass Defaults existieren
    if not DEFAULT_SETTINGS_PATH.exists():
        QMessageBox.critical(None, "Fehlende Defaults",
                             f"Default_Settings.json fehlt unter:\n{DEFAULT_SETTINGS_PATH}")
        sys.exit(1)

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()