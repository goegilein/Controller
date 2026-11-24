"""P3.3: machine profile – the controller's machine values from a profile file, BildHatcher's layout readable."""
import json
from dataclasses import fields
from pathlib import Path

import pytest

import PathManager
from machine_bridge import config_from_settings
from machine_core.profile import ProfileError, apply, find_profile, load_profile
from machine_core.worker import ArtisanConfig

BUNDLED = Path(__file__).resolve().parents[1] / "profiles"
BILDHATCHER = {  # the fields of BildHatcher's machine_profiles/snapmaker_artisan_40w.json (2.x, flat)
    "name": "Snapmaker Artisan 40W", "header": ["G90", "G21"], "footer": ["M5", "M9"],
    "laser_modes": {"variable": ["M4 P0"]}, "burn_power": " P{power} S{s}", "feedrate": 6000}


def machine(**changes):
    data = json.loads((BUNDLED / "snapmaker_artisan.json").read_text(encoding="utf-8"))["machine"]
    data.update(changes)
    return data


def write(tmp_path, data, name="m.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_bundled_profile_gives_todays_values():
    """Switching to the profile changes nothing on the machine: every value equals v2.0's built-in ones."""
    config = apply(load_profile(BUNDLED / "snapmaker_artisan.json"), ArtisanConfig())
    default = ArtisanConfig()
    assert {f.name: getattr(config, f.name) for f in fields(config)} == \
           {f.name: getattr(default, f.name) for f in fields(default)}


def test_bildhatcher_layout_with_a_machine_section(tmp_path):
    """BildHatcher 2.x profiles are flat; with a `machine` key the same file serves both programs."""
    profile = load_profile(write(tmp_path, {**BILDHATCHER, "machine": machine()}))
    assert profile.id == "snapmaker_artisan" and profile.name == "Snapmaker Artisan 40W"
    assert profile.gcode["feedrate"] == 6000 and "machine" not in profile.gcode
    nested = load_profile(write(tmp_path, {"name": "A", "gcode": {"feedrate": 1}, "machine": machine()}, "n.json"))
    assert nested.gcode == {"feedrate": 1}


@pytest.mark.parametrize("change, message", [
    ({"laser_off": []}, "laser_off: must not be empty"),
    ({"laser_off": None}, "laser_off: expected a list"),
    ({"work_area": {"x": [0, 400], "y": [0, 400]}}, "work_area needs x, y and z"),
    ({"work_area": {"x": [400, 0], "y": [0, 400], "z": [0, 400]}}, "min must be below max"),
    ({"toolheads": {"a": {"laser_offset": [0, 0, 0], "m1006_lines": 39},
                    "b": {"laser_offset": [1, 0, 0], "m1006_lines": 39}}}, "also used by a"),
    ({"toolheads": {"a": {"laser_offset": [0, 0]}}}, "laser_offset must be"),
    ({"limits": {"max_power_s": "255"}}, "expected a number"),
    ({"outputs": {"light": {"on": ["M2000 W1 P100"]}}}, "needs 'on' and 'off'"),
    ({"id": ""}, "machine.id missing"),
])
def test_a_wrong_profile_is_not_used_at_all(tmp_path, change, message):
    with pytest.raises(ProfileError, match=message):
        load_profile(write(tmp_path, {"name": "x", "machine": machine(**change)}))
    with pytest.raises(ProfileError, match="no 'machine' section"):
        load_profile(write(tmp_path, BILDHATCHER))


def test_first_use_moves_the_calibrated_settings_into_the_users_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(PathManager, "USER_DIR", tmp_path)
    calibrated = Settings(**{"artisan.laser1064.laser_offset": [21.5, -11.0, 0.2]})
    config = config_from_settings(calibrated)
    copy = tmp_path / "profiles" / "snapmaker_artisan.json"
    assert config.profile_path == str(copy) and config.profile_error is None
    assert config.laser_offsets["laser1064"] == (21.5, -11.0, 0.2)                  # calibration kept
    assert json.loads(copy.read_text(encoding="utf-8"))["machine"]["toolheads"]["laser1064"]["laser_offset"] == \
           [21.5, -11.0, 0.2]
    # from now on the profile counts: an edit there is used, the old settings key no longer
    data = json.loads(copy.read_text(encoding="utf-8"))
    data["machine"]["work_area"]["x"] = [0, 380]
    copy.write_text(json.dumps(data), encoding="utf-8")
    config = config_from_settings(Settings(**{"artisan.laser1064.laser_offset": [0, 0, 0]}))
    assert config.work_area[0] == (0, 380) and config.laser_offsets["laser1064"] == (21.5, -11.0, 0.2)


def test_a_broken_profile_falls_back_to_the_settings_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(PathManager, "USER_DIR", tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "snapmaker_artisan.json").write_text("{ broken", encoding="utf-8")
    config = config_from_settings(Settings(**{"artisan.laser455.laser_offset": [-20.0, 0, 0]}))
    assert "machine profile not used" in config.profile_error and config.profile_path is None
    assert config.laser_offsets["laser455"] == (-20.0, 0, 0)
    config = config_from_settings(Settings(**{"artisan.machine_profile": "nope"}))
    assert "no machine profile 'nope'" in config.profile_error


def test_find_profile_copies_once(tmp_path):
    path, created = find_profile("snapmaker_artisan", tmp_path, BUNDLED)
    assert created and path.parent == tmp_path
    assert find_profile("snapmaker_artisan", tmp_path, BUNDLED) == (path, False)
