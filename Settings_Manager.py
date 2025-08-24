# settings_manager.py
from __future__ import annotations
import json, shutil, tempfile, pathlib, threading
from jsonschema import validate, Draft202012Validator, FormatChecker
from typing import Any, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal

class SettingsManager(QObject):
    settingChanged = pyqtSignal(str, object)     # path, value
    settingsReplaced = pyqtSignal()              # fired after load()
    settingValidationError = pyqtSignal(str)  # exception object

    _instance: Optional["SettingsManager"] = None

    def __init__(self, default_settings_path: pathlib.Path, schema_path=pathlib.Path, use_validation=False):
        super().__init__()
        if hasattr(self, "_initialized"): return
        self._initialized = True
        self._lock = threading.RLock()
        self._default_settings_path = default_settings_path
        self._schema_validator = Draft202012Validator(self._load_json(schema_path), format_checker=FormatChecker()) if use_validation else None
        self._defaults = self._load_json(default_settings_path)
        self._active_settings: Dict[str, Any] = {}          # current user layer
        self._session: Dict[str, Any] = {}       # ephemeral overrides
        self._last_active_file: Optional[pathlib.Path] = None
        self.load_user_file(default_settings_path)

    # ---------- Public API ----------
    def get(self, path: str, fallback: Any=None) -> Any:
        with self._lock:
            if (v := self._get_from(self._session, path)) is not None: return v
            if (v := self._get_from(self._active_settings, path))    is not None: return v
            return self._get_from(self._defaults, path, fallback)

    def set(self, path: str, value: Any, layer: str="user", persist: bool=True):
        """ layer: 'session' | 'user' """
        with self._lock:
            # 1) build merged preview for validation
            merged = self.merged()
            self._set_in(merged, path, value)
            self._validate(merged)

            # 2) write to target layer
            target = self._session if layer == "session" else self._active_settings
            self._set_in(target, path, value)

            # 3) persist (only user layer)
            # if persist and layer == "user" and self._last_user_file:
            #     self._atomic_write_json(self._last_user_file, self._user)

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
            return deep_merge(deep_merge(self._defaults, self._active_settings), self._session)

    def load_user_file(self, path: pathlib.Path):
        data = self._load_json(path)
        # optional: migration by schema_version
        merged_preview = self._merge_preview(data)
        self._validate(merged_preview)
        with self._lock:
            self._active_settings = data or {}
            self._last_active_file = path
        self.settingsReplaced.emit()
    
    def load_default(self):
        self.load_user_file(self._default_settings_path)

    def save_user_file_as(self, path: pathlib.Path):
        with self._lock:
            self._atomic_write_json(path, self._active_settings)
            self._last_active_file = path
        
    def save_default(self):
        self.save_user_file_as(self._default_settings_path)

    # def export_full_merged(self, path: pathlib.Path):
    #     with self._lock:
    #         self._atomic_write_json(path, self.merged())

    # ---------- Helpers ----------
    def _validate(self, merged: Dict[str, Any]):
        """Emit en error if validation finds one."""
        if not self._schema_validator:
            return []
        
        # Prefer iter_errors to collect all issues
        iter_errors = getattr(self._schema_validator, "iter_errors", None)
        if callable(iter_errors):
            if not list(iter_errors(merged)):
                return
            e= SettingsValidationError(list(iter_errors(merged)))
            self.settingValidationError.emit(e.message)
            return
        # Fallback to single validate()
        try:
            self._schema_validator.validate(merged)
        except Exception as e:
            self.settingValidationError.emit(e.message)

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
            raise RuntimeError(f"Cannot read file: {p}\n{e}") from e

        if not text.strip():
            # empty file -> treat like no defaults instead of failing
            return {}

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # precise error message with line/col
            raise RuntimeError(
                f"Invalid JSON in {p} (line {e.lineno}, row {e.colno}): {e.msg}"
            ) from e

    @staticmethod
    def _atomic_write_json(p: pathlib.Path, data: Dict[str, Any]):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # tmp = pathlib.Path(tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")[1])
        # try:
        #     tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        #     shutil.move(str(tmp), str(p))
        # finally:
        #     if tmp.exists():
        #         tmp.unlink(missing_ok=True)
    
from typing import List
#from jsonschema.exceptions import ValidationError as _JSValidationError


class SettingsValidationError(Exception):
    """Raised when settings JSON fails schema validation."""
    def __init__(self, errors: List[Exception]):
        self.error = errors[0]
        msg_lines = []
        # for e in errors:
            # jsonschema ValidationError has .path and .message
        path = ""
        message = str(self.error)
        try:
            path = ".".join(str(p) for p in getattr(self.error, "path", [])) or "<root>"
            message = getattr(self.error, "message", message)
        except Exception:
            pass
        msg_lines.append(f"{path}: {message}")
        super().__init__("\n".join(msg_lines))
        self.message = "\n".join(msg_lines)