"""Commands (UI -> machine) and events (machine -> UI) as plain dataclasses (REVISION_PLAN.md P2.1, rule 3).

Every message serializes to JSON as {"type": <class name>, ...fields}, so the transport between UI and core
(Qt signals today, IPC later) can be swapped without touching either side.
"""
import json
from dataclasses import asdict, dataclass, field, fields

_TYPES = {}


def _message(cls):
    cls = dataclass(frozen=True)(cls)
    _TYPES[cls.__name__] = cls
    return cls


def to_json(message) -> str:
    return json.dumps({"type": type(message).__name__, **asdict(message)})


def from_json(text: str):
    data = json.loads(text)
    cls = _TYPES[data.pop("type")]
    for f in fields(cls):  # JSON has no tuples
        if isinstance(data.get(f.name), list) and f.type in ("tuple", tuple):
            data[f.name] = tuple(data[f.name])
    return cls(**data)


# ------------------------------------------------------------------ commands

@_message
class Connect:
    port: str
    baudrate: int = 115200


@_message
class Disconnect:
    pass


@_message
class Home:
    axes: str = ""  # "" = all, else e.g. "Z"


@_message
class Jog:
    """Relative step move of one axis."""
    axis: str
    distance: float  # mm, signed
    speed: float     # mm/s


@_message
class JogStart:
    """Continuous jog while a button is held; ended by JogStop."""
    axis: str
    direction: int   # +1 / -1
    speed: float


@_message
class JogStop:
    pass


@_message
class MoveTo:
    """Move to a position. frame: "absolute" (machine, app coordinates), "work" (current work position), "relative"."""
    x: float
    y: float
    z: float
    speed: float = None
    frame: str = "absolute"
    z_safe: bool = True


@_message
class SetWorkPosition:
    pass


@_message
class SetOutput:
    """Machine outputs: "crosshair", "light", "fan", "air_assist"."""
    name: str
    on: bool


@_message
class StartJob:
    path: str


@_message
class Pause:
    pass


@_message
class Resume:
    pass


@_message
class Stop:
    """Controlled stop: quick stop, laser off, connection stays (C2). The UI asks for confirmation first."""
    pass


@_message
class EmergencyStop:
    """Firmware halt (M112); the machine needs a restart (C2). The UI asks for confirmation first."""
    pass


@_message
class AcknowledgeError:
    """Leave the error state – the only way back to idle after an error; nothing resumes on its own."""
    pass


# ------------------------------------------------------------------ events

@_message
class StateChanged:
    state: str
    reason: str = ""


@_message
class PositionChanged:
    work: tuple          # (x, y, z) in work coordinates (what M114 reports)
    absolute: tuple      # (x, y, z) in absolute app coordinates (work + origin offset)


@_message
class ToolheadDetected:
    name: str            # "laser1064" / "laser455"
    laser_offset: tuple


@_message
class JobProgress:
    step: int
    segment: int
    remaining_s: float


@_message
class LogLine:
    text: str
    level: str = "info"  # "info" / "warning" / "error"


@_message
class ErrorRaised:
    message: str
    code: str = ""
