"""J-code / G-code reading for the job runner (REVISION_PLAN.md P2.4). Pure functions, no Qt.

J-code v0 (as written by BildHatcher `Parsing.save_jcode`):
    J0 X<x> Y<y> Z<z> R<deg>   reference position of the following segment, relative to the process step
    J1 <file>                  G-code segment; relative paths are resolved against the J-code's folder (B09)
A `.nc` file is one segment at J0 0 0 0 0.

G-code is read into moves in the segment's raw coordinates (absolute, G91 resolved). Supported: G0 / G1, G4, G21,
G90 / G91, M-codes. Refused at load time (the job would not do what the file says): G2 / G3, G28, G92, G53–G59.
Lines that are not commands (BildHatcher's `===;start of new Processblock===`) are skipped with a warning (B24).
Long moves are split into pieces of at most 1 s, like v1.0, so pause reacts quickly and progress is smooth.
"""
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_PIECE_S = 1.0
_COMMAND = re.compile(r"^[GMT]\d+(\.\d+)?$", re.IGNORECASE)
_REFUSED = {"G2", "G3", "G20", "G28", "G92", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}  # G20: inch


class JobError(Exception):
    pass


@dataclass
class Move:
    """A G0 / G1 in raw segment coordinates."""
    code: str                 # "G0" / "G1"
    target: tuple             # (x, y, z) raw, absolute
    axes: str                 # axes written in the line, e.g. "XY"
    words: list               # other words in their original order (F, S, P, ...)
    duration: float           # s, estimate


@dataclass
class Other:
    """Any other command line, sent as it is."""
    text: str
    duration: float = 0.01


@dataclass
class Segment:
    ref: tuple                # J0 (x, y, z, r)
    items: list               # Move / Other
    source: str
    warnings: list = field(default_factory=list)

    @property
    def duration(self):
        return sum(i.duration for i in self.items)


def strip_comment(line: str) -> str:
    """G-code comments: `( ... )` and everything after `;`."""
    line = re.sub(r"\([^)]*\)", "", line)
    return line.split(";", 1)[0].strip()


def strip_jcode_comment(line: str) -> str:
    """J-code comments: only `;` – parentheses are allowed in J1 file names (e.g. `job (1).nc`)."""
    return line.split(";", 1)[0].strip()


def read_gcode(path, start=(0.0, 0.0, 0.0)) -> Segment:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise JobError(f"cannot read G-code file {path}: {e}") from e
    items, warnings = [], []
    pos = list(start)
    feed = 6000.0
    absolute = True
    for number, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw)
        if not line:
            continue
        parts = line.split()
        code = parts[0].upper()
        if not _COMMAND.match(code):
            warnings.append(f"{path.name}:{number}: not a command, skipped: {line!r}")
            continue
        code = code[0] + str(float(code[1:])).removesuffix(".0")  # G00 -> G0, G1.0 -> G1
        if code in _REFUSED:
            raise JobError(f"{path.name}:{number}: {code} is not supported in a job ({line!r})")
        if code == "G90":
            absolute = True
            continue
        if code == "G91":
            absolute = False
            continue
        if code not in ("G0", "G1"):
            items.append(Other(line))
            continue
        new, axes, words = list(pos), "", []
        for word in parts[1:]:
            letter = word[0].upper()
            if letter in "XYZ":
                try:
                    value = float(word[1:])
                except ValueError as e:
                    raise JobError(f"{path.name}:{number}: bad number {word!r}") from e
                i = "XYZ".index(letter)
                new[i] = value if absolute else pos[i] + value
                axes += letter
            else:
                if letter == "F":
                    feed = float(word[1:])
                words.append(word)
        duration = math.dist(pos, new) / feed * 60 if feed > 0 else 0.01
        pieces = math.ceil(duration / MAX_PIECE_S) if duration > MAX_PIECE_S else 1
        for k in range(1, pieces + 1):
            point = tuple(p + (n - p) * k / pieces for p, n in zip(pos, new))
            items.append(Move(code, point, axes, words, max(duration / pieces, 0.01)))
        pos = new
    return Segment((0.0, 0.0, 0.0, 0.0), items, str(path), warnings)


def read_job_file(path) -> list:
    """Segments of a `.nc` or `.jcode` file. Raises JobError for anything that would make the job incomplete."""
    path = Path(path)
    if path.suffix.lower() != ".jcode":
        return [read_gcode(path)]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise JobError(f"cannot read J-code file {path}: {e}") from e
    segments, ref = [], (0.0, 0.0, 0.0, 0.0)
    for number, raw in enumerate(lines, 1):
        line = strip_jcode_comment(raw)
        if not line:
            continue
        parts = line.split(None, 1)
        if parts[0].upper() == "J0":
            values = dict.fromkeys("XYZR", 0.0)  # missing axes are 0, not the previous value (B17)
            for word in parts[1].split() if len(parts) > 1 else []:
                letter = word[0].upper()
                if letter not in values:
                    raise JobError(f"{path.name}:{number}: unknown J0 word {word!r}")
                try:
                    values[letter] = float(word[1:])
                except ValueError as e:
                    raise JobError(f"{path.name}:{number}: bad number {word!r}") from e
            ref = tuple(values[a] for a in "XYZR")
        elif parts[0].upper() == "J1":
            if len(parts) < 2:
                raise JobError(f"{path.name}:{number}: J1 without a file")
            target = Path(parts[1].strip())
            if not target.is_absolute():
                target = path.parent / target
            if not target.exists():
                raise JobError(f"{path.name}:{number}: G-code file not found: {target}")
            segment = read_gcode(target)
            segment.ref = ref
            segments.append(segment)
        else:
            raise JobError(f"{path.name}:{number}: unknown J-code line {line!r}")
    if not segments:
        raise JobError(f"{path.name}: no G-code segment (J1) in the file")
    return segments
