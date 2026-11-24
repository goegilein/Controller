"""Qt side of the machine core (REVISION_PLAN.md P2.8).

`MachineBridge` owns the `MachineWorker` and brings its events into the UI thread (a queued Qt signal), so widgets
are only touched from the UI thread (B07). `ArtisanFacade` offers the methods of the old `ArtisanController` that the
UI modules call, but every method only submits a command or reads cached state – no serial I/O in the UI thread (B12).
`RotaryFacade` does the same for the rotary stages (old `RotMotorCotroller` API on top of `machine_core.stages`).

Coordinates: `abs_position` / `get_absolute_position()` are machine coordinates (C5); `current_position` /
`get_position()` are relative to the work position, which only lives in the app (no G92).
"""
import json
import time

from PyQt6 import QtCore

import protocol_log
from machine_core import messages as m
from machine_core import profile
from machine_core.stages import LoopRecorder, RotaryStages, ScservoBus, SimStageBus, StageError
from machine_core.worker import SIMULATOR_PORT, ArtisanConfig, MachineWorker

PROCESS_STATES = {"running": "Running", "paused": "Paused"}  # everything else is "Idle" for the old UI


def config_from_settings(settings):
    get = settings.get if settings else (lambda key, default=None: default)
    config = ArtisanConfig()
    config.baudrate = get("artisan.baudrate", config.baudrate)
    config.default_speed = get("artisan.motion.default_speed", config.default_speed)
    config.max_z_speed = get("artisan.motion.max_z_speed", config.max_z_speed)  # v1.0 read a misspelt key (B16)
    config.laser_offsets = {head: tuple(get(f"artisan.{head}.laser_offset", list(offset)))
                            for head, offset in config.laser_offsets.items()}
    _apply_profile(config, get)
    # P3.4: one run log per job; default folder Documents/MachineControl/runs, `run_log.folder` overrides it
    from PathManager import USER_DIR, get_base_dir
    config.run_log_dir = str(get("run_log.folder", "") or USER_DIR / "runs")
    try:
        v = json.loads((get_base_dir() / "version.json").read_text(encoding="utf-8"))
        config.app_version = f"{v['major']}.{v['minor']}.{v['patch']}"
    except (OSError, ValueError, KeyError):
        pass
    return config


# settings keys of v1.0 / 2.0 that the machine profile replaces (P3.3): settings key -> machine section key
LEGACY_KEYS = {"artisan.baudrate": "baudrate",
               "artisan.motion.default_speed": "limits.default_speed",
               "artisan.motion.max_z_speed": "limits.max_z_speed",
               "artisan.laser1064.laser_offset": "toolheads.laser1064.laser_offset",
               "artisan.laser455.laser_offset": "toolheads.laser455.laser_offset"}


def _apply_profile(config, get):
    """P3.3: the machine values come from the machine profile `artisan.machine_profile` (Documents/MachineControl/
    profiles). The first time the user's copy is made, the values in the settings are moved into it, so a calibrated
    laser offset is kept. If the profile cannot be used, the settings' values stay and `profile_error` says why."""
    from PathManager import USER_DIR, get_base_dir
    name = get("artisan.machine_profile", "snapmaker_artisan")
    try:
        path, created = profile.find_profile(name, USER_DIR / "profiles", get_base_dir() / "profiles")
        if created:
            moved = {key: get(old) for old, key in LEGACY_KEYS.items() if get(old) is not None}
            profile.update_machine_values(path, moved)
            protocol_log.note("artisan", f"machine profile {path} created, settings moved into it: {sorted(moved)}")
        loaded = profile.load_profile(path)
        before = {old: get(old) for old in LEGACY_KEYS}
        profile.apply(loaded, config)
        config.profile_path = str(path)
        differs = [old for old, value in before.items() if value is not None and not _same(value, _machine_value(
            loaded.machine, LEGACY_KEYS[old]))]
        if differs:
            protocol_log.note("artisan", f"settings {differs} differ from the machine profile {path} – the profile is used")
    except (profile.ProfileError, OSError, ValueError, KeyError) as e:
        config.profile_error = f"machine profile not used ({e}); values from the settings"
        protocol_log.note("artisan", config.profile_error)


def _machine_value(machine, dotted):
    node = machine
    for part in dotted.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


class MachineBridge(QtCore.QObject):
    """Runs the worker; `event` is emitted in the UI thread for every core event."""
    event = QtCore.pyqtSignal(object)
    _from_worker = QtCore.pyqtSignal(object)

    def __init__(self, config=None, rotary=None, transport_factory=None, parent=None):
        super().__init__(parent)
        self._from_worker.connect(self._relay)  # receiver lives in the UI thread -> queued
        self._closed = False
        # a bound method keeps this QObject alive as long as the worker can still emit (a bound signal does not)
        self.worker = MachineWorker(on_event=self._from_worker_thread, config=config or ArtisanConfig(),
                                    transport_factory=transport_factory, rotary=rotary)

    def _from_worker_thread(self, event):
        if not self._closed:
            self._from_worker.emit(event)

    def _relay(self, event):
        self.event.emit(event)

    def submit(self, command):
        self.worker.submit(command)

    def shutdown(self):
        self.worker.shutdown()
        self._closed = True


class ArtisanFacade:
    """The old ArtisanController API, as far as the UI modules use it."""

    def __init__(self, bridge: MachineBridge, settings=None, ask_home=None):
        self.bridge = bridge
        self.s = settings
        self.ask_home = ask_home or _ask_home_dialog
        self.state = "disconnected"
        self.abs_position = None               # machine coordinates
        self._current_position = [0.0, 0.0, 0.0]
        self.work_position = (0.0, 0.0, 0.0)
        self._tool_head = None
        self._laser_offset = None
        self._asked_home = False
        self.position_changed_callbacks = []
        self.log_callback = None
        self.process_state_callbacks = []
        self.state_callbacks = []              # (state, reason) – new UI parts
        self.error_callbacks = []              # (message) – new UI parts
        self.progress_callbacks = []           # (JobProgress)
        self.load_settings()
        if settings is not None:
            settings.settingChanged.connect(self.load_settings)
            settings.settingsReplaced.connect(self.load_settings)
        bridge.event.connect(self._on_event)

    def load_settings(self, *_):
        get = self.s.get if self.s else (lambda key, default=None: default)
        self.port = get("artisan.port", "COM6")
        self.speed = get("artisan.motion.default_speed", 30)
        self.step_width = get("artisan.motion.default_step_width", 10)
        if self.state in ("disconnected",):  # the worker's config is only replaced while disconnected (B16)
            self.bridge.worker.config = config_from_settings(self.s)

    # ------------------------------------------------------------------ events (UI thread)
    def _on_event(self, e):
        try:
            self._handle_event(e)
        except Exception as exc:  # PyQt6 aborts the whole app on an exception in a slot
            protocol_log.note("artisan", f"UI event handler failed on {e!r}: {exc!r}")
            print(f"UI event handler failed: {exc!r}")

    def _handle_event(self, e):
        if isinstance(e, m.StateChanged):
            old_process = self.process_state
            self.state = e.state
            for cb in self.state_callbacks:
                cb(e.state, e.reason)
            if self.process_state != old_process:
                for cb in self.process_state_callbacks:
                    cb(self.process_state)
            if e.state == "disconnected":
                self._asked_home = False
            if e.state == "idle" and not self._asked_home and self._tool_head:
                self._asked_home = True
                if not self.bridge.worker.homed_all and self.ask_home():
                    self.home_axis()
        elif isinstance(e, m.PositionChanged):
            self.abs_position = list(e.absolute)
            self.work_position = tuple(a - w for a, w in zip(e.absolute, e.work))
            self.current_position = list(e.work)
        elif isinstance(e, m.ToolheadDetected):
            self._tool_head = e.name
            self._laser_offset = list(e.laser_offset)
            self.last_log = f"toolhead {e.name} detected, laser offset {list(e.laser_offset)}"
        elif isinstance(e, m.LogLine):
            self.last_log = e.text if e.level == "info" else f"{e.level.upper()}: {e.text}"
        elif isinstance(e, m.ErrorRaised):
            self.last_log = f"ERROR: {e.message}"
            for cb in self.error_callbacks:
                cb(e.message)
        elif isinstance(e, m.JobProgress):
            for cb in self.progress_callbacks:
                cb(e)

    # ------------------------------------------------------------------ state, as the old controller had it
    @property
    def current_position(self):
        return self._current_position

    @current_position.setter
    def current_position(self, value):
        self._current_position = value
        for cb in self.position_changed_callbacks:
            cb(value)

    def add_position_changed_callback(self, callback):
        self.position_changed_callbacks.append(callback)

    @property
    def last_log(self):
        return getattr(self, "_last_log", "")

    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        if self.log_callback:
            self.log_callback(value)

    def set_log_callback(self, callback):
        self.log_callback = callback

    @property
    def process_state(self):
        return PROCESS_STATES.get(self.state, "Idle")

    def set_process_state_callback(self, callback):
        self.process_state_callbacks.append(callback)

    @property
    def connected(self):
        return self.state not in ("disconnected", "connecting")

    def is_connection_active(self):
        return self.connected

    @property
    def laser_offset(self):
        return self._laser_offset

    @property
    def tool_head(self):
        return self._tool_head

    @property
    def is_homed(self):
        return self.bridge.worker.homed_all

    def get_position(self):
        """Cached position relative to the work position (no I/O; the worker polls M114 while idle)."""
        return list(self._current_position) if self.abs_position is not None else None

    def get_absolute_position(self):
        """Cached machine position (no I/O)."""
        return list(self.abs_position) if self.abs_position is not None else None

    # ------------------------------------------------------------------ commands
    def _submit(self, command):
        self.bridge.submit(command)

    def connect(self):
        if self.connected:
            self.last_log = "Artisan already connected."
            return
        self._tool_head = self._laser_offset = None
        if self.s is not None:                 # disconnected: a changed machine profile is read again (P3.3)
            self.bridge.worker.config = config_from_settings(self.s)
        config = self.bridge.worker.config
        if config.profile_error:
            self.last_log = f"WARNING: {config.profile_error}"
        self._submit(m.Connect(self.port, config.baudrate))

    def disconnect(self):
        self._submit(m.Disconnect())

    def home_axis(self, axis="", job_save=False):
        self._submit(m.Home(axis if isinstance(axis, str) else ""))  # clicked() passes a bool (v1.0 sent "G28 False")

    def move_axis_step(self, axis, direction, distance=None, speed=None, job_save=False):
        distance = self.step_width if distance is None else distance
        self._submit(m.Jog(axis, direction * distance, speed or self.speed))

    def move_axis_continuous(self, axis, direction, speed=None, job_save=False):
        self._submit(m.JogStart(axis, direction, speed or self.speed))

    def stop_axis(self):
        self._submit(m.JogStop())

    def move_axis_to(self, mode, x, y, z, speed=None, job_save=False):
        """v1.0: "absolute" = work coordinates in one G0 (not Z-safe), "relative" = from here."""
        if mode not in ("absolute", "relative"):
            self.last_log = "Error: Invalid move mode. Must be 'absolute' or 'relative'."
            return
        frame = "work" if mode == "absolute" else "relative"
        self._submit(m.MoveTo(x, y, z, speed or self.speed, frame=frame, z_safe=False))

    def move_axis_absolute(self, x, y, z, speed=None, z_save=True, job_save=False):
        self._submit(m.MoveTo(x, y, z, speed or self.speed, frame="absolute", z_safe=z_save))

    def move_to_work_position(self, speed=None, job_save=False):
        self.move_axis_to("absolute", 0, 0, 0, speed=speed)

    def set_work_position(self, job_save=False):
        self._submit(m.SetWorkPosition())

    def set_speed(self, speed, job_save=False):
        if speed < 0 or speed > 100:
            self.last_log = "Error: Speed must be between 0 and 100."
            return
        self.speed = speed

    def set_step_width(self, step_width):
        if step_width < 0 or step_width > 100:
            self.last_log = "Error: Step width must be between 0 and 100."
            return
        self.step_width = step_width

    def _output(self, name, state):
        self._submit(m.SetOutput(name, state == "on"))

    def set_laser_crosshair(self, state):
        self._output("crosshair", state)

    def set_enclosure_light(self, state):
        self._output("light", state)

    def set_enclosure_fan(self, state):
        self._output("fan", state)

    def set_air_assist(self, state):
        self._output("air_assist", state)

    def stop(self):
        """Software stop: quick stop, laser off; the head stays where it is."""
        self._submit(m.Stop())

    def emergency_stop(self):
        """M112: the firmware halts; restart the machine and reconnect."""
        self._submit(m.EmergencyStop())

    def acknowledge_error(self):
        self._submit(m.AcknowledgeError())


def _ask_home_dialog():
    from PyQt6.QtWidgets import QMessageBox
    answer = QMessageBox.question(None, "Homing Required",
                                  "Machine coordinates need homing (G28) after every connect.\nRun homing now?",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


class RotaryFacade(RotaryStages):
    """Rotary stages with the old RotMotorCotroller API (connect / disconnect never raise, callbacks, settings)."""

    def __init__(self, settings=None, bus_factory=None, **kw):
        super().__init__(bus_factory or self._make_bus, on_log=self._log, **kw)
        self.s = settings
        self.log_callbacks = []
        self.connected_callbacks = []
        self._last_log = ""
        self.load_settings()
        if settings is not None:
            settings.settingChanged.connect(self.load_settings)
            settings.settingsReplaced.connect(self.load_settings)

    def load_settings(self, *_):
        get = self.s.get if self.s else (lambda key, default=None: default)
        self.port = get("rotary_motors.port", "COM7")
        self.series = get("rotary_motors.series", "STS")
        self.gear_ratio = float(get("rotary_motors.gear_ratio", 3))     # applied on the next connect
        self.gear_ratios = {int(k): float(v) for k, v in (get("rotary_motors.gear_ratios", {}) or {}).items()}
        mode = get("rotary_motors.control_mode", "wheel")     # C16: "position" after the hardware test
        self.control_mode = mode if mode in ("wheel", "position") else "wheel"
        self.record_loop = bool(get("rotary_motors.record_loop", False))

    def _make_bus(self):
        if self.port == SIMULATOR_PORT:
            return SimStageBus(ids=(1, 2), cycle_dt=self.loop_interval)  # one nominal cycle per loop (C16)
        return ScservoBus(self.port, self.series)

    @property
    def last_log(self):
        return self._last_log

    @last_log.setter
    def last_log(self, value):
        self._last_log = value
        for cb in self.log_callbacks:
            cb(value)

    def _log(self, text, level="info"):
        self.last_log = text if level == "info" else f"{level.upper()}: {text}"

    def set_log_callback(self, callback):
        self.log_callbacks.append(callback)

    def set_connected_callback(self, callback):
        self.connected_callbacks.append(callback)

    def _notify_connected(self):
        for cb in self.connected_callbacks:
            cb(self.connected)

    def connect(self):
        if self.connected:
            self.last_log = "Rotary Motor Board already connected."
            return
        try:
            if self.record_loop and self.recorder is None:
                from PathManager import USER_DIR
                self.recorder = LoopRecorder(USER_DIR / "logs" / time.strftime("rotary_loop_%Y%m%d_%H%M%S.csv"))
            super().connect()
            protocol_log.note("rotary", f"connected on {self.port} ({self.series}, {self.control_mode} mode), "
                                        f"motors {[mo.ID for mo in self.motors]}")
        except Exception as e:
            self.bus = None
            if self.recorder is not None:
                self.recorder.close()
                self.recorder = None
            self.last_log = f"Rotary Motor Board connection error: {e}."
            protocol_log.note("rotary", f"connect failed on {self.port}: {e!r}")
        self._notify_connected()

    def disconnect(self):
        if not self.connected:
            self.last_log = "No Rotary Motor Board connected."
            return
        super().disconnect()
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
        protocol_log.note("rotary", "disconnected")
        self._notify_connected()

    def is_connection_active(self):
        return self.connected and not self.fault

    def get_motor_by_id(self, sid):
        return None if sid is None else self._motors(sid)

    def get_motor_ids(self):
        return [mo.ID for mo in self.motors]

    def set_speed(self, sid, speed):
        with self.lock:
            for mo in self._motors(sid):
                mo.speed_limit = speed

    def set_acc(self, sid, acc):
        with self.lock:
            for mo in self._motors(sid):
                mo.acc = acc

    def move_to_angle(self, sid, angle, wait_for_position=False, timeout=None, cancel=None):
        protocol_log.note("rotary", f"move motor {sid} to {angle} deg (wait={wait_for_position})")
        try:
            return super().move_to_angle(sid, angle, wait_for_position, timeout, cancel)
        except StageError as e:
            if wait_for_position:
                raise                      # the job runner turns it into a machine error
            self.last_log = f"ERROR: {e}"  # a button click must not raise into Qt
            return False
