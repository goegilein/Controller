"""Machine profile (REVISION_PLAN.md P3.3, C10): what the controller needs to know about a machine, from a file.

One JSON file per machine in `Documents\\MachineControl\\profiles` (the bundled ones in `profiles/` are copied there
on first use; the user edits the copy). Format, see docs/MACHINE_PROFILE.md:

    {"name": ..., "gcode": {...BildHatcher's profile fields...}, "machine": {...this module...}}

BildHatcher 2.x has no `gcode` section, its fields are on the top level. That layout is read too: the top-level
fields are then the `gcode` section, so the same file can serve both programs until v3.0 (BildHatcher logs an
unknown `machine` key and ignores it). The controller only uses `machine`; `gcode` stays BildHatcher's.

A profile is checked completely when it is loaded – a profile that is wrong in one place is not used at all.
"""
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path


class ProfileError(Exception):
    pass


@dataclass
class MachineProfile:
    id: str
    name: str
    machine: dict
    gcode: dict = field(default_factory=dict)
    path: Path = None


def _number(value, where, low=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{where}: expected a number, got {value!r}")
    if low is not None and value < low:
        raise ProfileError(f"{where}: must be at least {low}, got {value!r}")
    return float(value)


def _lines(value, where, allow_empty=False):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ProfileError(f"{where}: expected a list of G-code lines")
    if not value and not allow_empty:
        raise ProfileError(f"{where}: must not be empty")
    return tuple(v.split(";", 1)[0].strip() for v in value)


def _check(machine, where):
    """The `machine` section, checked; returns the values in the form ArtisanConfig uses."""
    if not isinstance(machine, dict):
        raise ProfileError(f"{where}: no 'machine' section")
    out = {}
    if not isinstance(machine.get("id"), str) or not machine["id"].strip():
        raise ProfileError(f"{where}: machine.id missing")
    out["machine_id"] = machine["id"].strip()
    area = machine.get("work_area")
    if not isinstance(area, dict) or set(area) != {"x", "y", "z"}:
        raise ProfileError(f"{where}: machine.work_area needs x, y and z as [min, max] in mm")
    ranges = []
    for axis in "xyz":
        r = area[axis]
        if not isinstance(r, list) or len(r) != 2:
            raise ProfileError(f"{where}: machine.work_area.{axis} must be [min, max]")
        low, high = (_number(v, f"{where}: machine.work_area.{axis}") for v in r)
        if low >= high:
            raise ProfileError(f"{where}: machine.work_area.{axis}: min must be below max")
        ranges.append((low, high))
    out["work_area"] = tuple(ranges)
    limits = machine.get("limits", {})
    if not isinstance(limits, dict):
        raise ProfileError(f"{where}: machine.limits must be an object")
    for key, attr in (("max_power_s", "max_power_s"), ("max_power_p", "max_power_p"),
                      ("default_speed", "default_speed"), ("max_z_speed", "max_z_speed")):
        if key in limits:
            out[attr] = _number(limits[key], f"{where}: machine.limits.{key}", low=0)
    if limits.get("max_feed") is not None:
        out["max_feed"] = _number(limits["max_feed"], f"{where}: machine.limits.max_feed", low=0)
    if "baudrate" in machine:
        out["baudrate"] = int(_number(machine["baudrate"], f"{where}: machine.baudrate", low=1))
    heads = machine.get("toolheads")
    if not isinstance(heads, dict) or not heads:
        raise ProfileError(f"{where}: machine.toolheads missing")
    offsets, detect = {}, {}
    for head, spec in heads.items():
        w = f"{where}: machine.toolheads.{head}"
        if not isinstance(spec, dict):
            raise ProfileError(f"{w}: must be an object")
        offset = spec.get("laser_offset")
        if not isinstance(offset, list) or len(offset) != 3:
            raise ProfileError(f"{w}.laser_offset must be [x, y, z] in mm")
        offsets[head] = tuple(_number(v, f"{w}.laser_offset") for v in offset)
        lines = spec.get("m1006_lines")
        if lines is not None:
            n = int(_number(lines, f"{w}.m1006_lines", low=1))
            if n in detect:
                raise ProfileError(f"{w}.m1006_lines {n} is also used by {detect[n]}")
            detect[n] = head
    out["laser_offsets"], out["toolhead_line_count"] = offsets, detect
    # safety rule: the controller must always be able to switch the laser off
    out["laser_off"] = _lines(machine.get("laser_off"), f"{where}: machine.laser_off")
    outputs = machine.get("outputs", {})
    if not isinstance(outputs, dict):
        raise ProfileError(f"{where}: machine.outputs must be an object")
    out["outputs"] = {}
    for name, pair in outputs.items():
        if not isinstance(pair, dict) or set(pair) != {"on", "off"}:
            raise ProfileError(f"{where}: machine.outputs.{name} needs 'on' and 'off' lines")
        on = _lines(pair["on"], f"{where}: machine.outputs.{name}.on")
        off = _lines(pair["off"], f"{where}: machine.outputs.{name}.off")
        if len(on) != 1 or len(off) != 1:
            raise ProfileError(f"{where}: machine.outputs.{name}: one line each for on and off")
        out["outputs"][name] = (on[0], off[0])
    return out


def load_profile(path) -> MachineProfile:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProfileError(f"cannot read machine profile {path}: {e}") from e
    if not isinstance(data, dict):
        raise ProfileError(f"{path.name}: not a JSON object")
    machine = data.get("machine")
    _check(machine, path.name)
    gcode = data["gcode"] if "gcode" in data else {k: v for k, v in data.items() if k not in ("machine", "name")}
    return MachineProfile(machine["id"].strip(), data.get("name") or machine["id"], machine, gcode, path)


def apply(profile: MachineProfile, config):
    """Writes the profile's machine values into an ArtisanConfig (in place) and returns it."""
    for attr, value in _check(profile.machine, profile.path.name if profile.path else profile.id).items():
        setattr(config, attr, value)
    return config


def find_profile(name, user_dir, bundled_dir):
    """(path, created) of profile `name` (file name without .json): the user's copy, made from the bundled one
    first (created = True only then)."""
    user_dir, bundled_dir = Path(user_dir), Path(bundled_dir)
    target = user_dir / f"{name}.json"
    if target.exists():
        return target, False
    bundled = bundled_dir / f"{name}.json"
    if not bundled.exists():
        raise ProfileError(f"no machine profile {name!r} in {user_dir} or {bundled_dir}")
    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, target)
    except OSError:
        return bundled, False       # read-only user folder: use the bundled profile
    return target, True


def update_machine_values(path, values):
    """Write `values` ({dotted key in the machine section: value}) into a profile file (the one-time migration)."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, value in values.items():
        node = data["machine"]
        *parents, last = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
