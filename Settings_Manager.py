# settings_manager.py
from __future__ import annotations
import json, shutil, tempfile, pathlib, threading
from typing import Any, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal

class SettingsManager(QObject):
    settingChanged = pyqtSignal(str, object)     # path, value
    settingsReplaced = pyqtSignal()              # fired after load()

    _instance: Optional["SettingsManager"] = None

    # def __new__(cls, *args, **kwargs):
    #     if cls._instance is None:
    #         cls._instance = super().__new__(cls)
    #     return cls._instance

    def __init__(self, default_path: pathlib.Path, schema_validator=None):
        super().__init__()
        if hasattr(self, "_initialized"): return
        self._initialized = True
        self._lock = threading.RLock()
        self._default_path = default_path
        self._schema_validator = schema_validator
        self._defaults = self._load_json(default_path)
        self._user: Dict[str, Any] = {}          # current user layer
        self._session: Dict[str, Any] = {}       # ephemeral overrides
        self._last_user_file: Optional[pathlib.Path] = None

    # ---------- Public API ----------
    def get(self, path: str, fallback: Any=None) -> Any:
        with self._lock:
            if (v := self._get_from(self._session, path)) is not None: return v
            if (v := self._get_from(self._user, path))    is not None: return v
            return self._get_from(self._defaults, path, fallback)

    def set(self, path: str, value: Any, layer: str="user", persist: bool=True):
        """ layer: 'session' | 'user' """
        with self._lock:
            # 1) build merged preview for validation
            merged = self.merged()
            self._set_in(merged, path, value)
            self._validate(merged)

            # 2) write to target layer
            target = self._session if layer == "session" else self._user
            self._set_in(target, path, value)

            # 3) persist (only user layer)
            if persist and layer == "user" and self._last_user_file:
                self._atomic_write_json(self._last_user_file, self._user)

        self.settingChanged.emit(path, value)

    def merged(self) -> Dict[str, Any]:
        with self._lock:
            def deep_merge(a, b):
                if isinstance(a, dict) and isinstance(b, dict):
                    out = dict(a)
                    for k, v in b.items():
                        out[k] = deep_merge(out.get(k), v)
                    return out
                return b if b is not None else a
            return deep_merge(deep_merge(self._defaults, self._user), self._session)

    def load_user_file(self, path: pathlib.Path):
        data = self._load_json(path)
        # optional: migration by schema_version
        merged_preview = self._merge_preview(data)
        self._validate(merged_preview)
        with self._lock:
            self._user = data or {}
            self._last_user_file = path
        self.settingsReplaced.emit()

    def save_user_file_as(self, path: pathlib.Path):
        with self._lock:
            self._atomic_write_json(path, self._user)
            self._last_user_file = path

    def export_full_merged(self, path: pathlib.Path):
        with self._lock:
            self._atomic_write_json(path, self.merged())

    # ---------- Helpers ----------
    def _validate(self, merged: Dict[str, Any]):
        if self._schema_validator:
            self._schema_validator(merged)  # raise on error

    def _merge_preview(self, user_layer: Dict[str, Any]):
        def deep_merge(a, b):
            if isinstance(a, dict) and isinstance(b, dict):
                out = dict(a)
                for k, v in b.items():
                    out[k] = deep_merge(out.get(k), v)
                return out
            return b if b is not None else a
        return deep_merge(self._defaults, user_layer or {})

    @staticmethod
    def _get_from(root: Dict[str, Any], path: str, fallback=None):
        cur = root
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur: return fallback
            cur = cur[part]
        return cur

    @staticmethod
    def _set_in(root: Dict[str, Any], path: str, value: Any):
        cur = root
        parts = path.split(".")
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = value

    @staticmethod
    def _load_json(p: pathlib.Path) -> Dict[str, Any]:
        if not p.exists():
            return {}
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            raise RuntimeError(f"Kann Datei nicht lesen: {p}\n{e}") from e

        if not text.strip():
            # Leere Datei -> behandle wie keine Defaults statt Absturz
            return {}

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Präzise Fehlermeldung mit Zeile/Spalte
            raise RuntimeError(
                f"Ungültiges JSON in {p} (Zeile {e.lineno}, Spalte {e.colno}): {e.msg}"
            ) from e

    @staticmethod
    def _atomic_write_json(p: pathlib.Path, data: Dict[str, Any]):
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")[1])
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            shutil.move(str(tmp), str(p))
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)