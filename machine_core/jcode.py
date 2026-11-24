"""J-code / G-code reading for the job runner (REVISION_PLAN.md P2.4). Pure functions, no Qt.

J-code v0 (as written by BildHatcher `Parsing.save_jcode`):
    J0 X<x> Y<y> Z<z> R<deg>   reference position of the following segment, relative to the process step
    J1 <file>                  G-code segment; relative paths are resolved against the J-code's folder (B09)
A `.nc` file is one segment at J0 0 0 0 0.

J-code v0.1 (P3.2, docs/JCODE_SPEC.md section 2): optional header lines `JH <key>=<value>` before the first J0 / J1
(format version, creator, units, machine, toolhead, SHA-256 per J1 file). With a header, J1 paths must be relative and
stay inside the job folder, and every mismatch is refused. A file without a header is v0 and runs as before.

G-code is read into moves in the segment's raw coordinates (absolute, G91 resolved). Supported: G0 / G1, G4, G21,
G90 / G91, M-codes. Refused at load time (the job would not do what the file says): G2 / G3, G28, G92, G53–G59.
Lines that are not commands (BildHatcher's `===;start of new Processblock===`) are skipped with a warning (B24).
Long moves are split into pieces of at most 1 s, like v1.0, so pause reacts quickly and progress is smooth.
"""
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_PIECE_S = 1.0
_COMMAND = re.compile(r"^[GMT]\d+(\.\d+)?$", re.IGNORECASE)
_REFUSED = {"G2", "G3", "G20", "G28", "G92", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}  # G20: inch


class JobError(Exception):
    pass


HEADER_KEYS = {"jcode", "creator", "created", "units", "machine", "toolhead", "sha256"}
SUPPORTED_MAJOR = 0


@dataclass
class JobFile:
    segments: list
    header: dict = field(default_factory=dict)      # key -> value; "sha256" -> {path as written: hex}
    warnings: list = field(default_factory=list)


def _key(path_text: str) -> str:
    """How J1 paths and sha256 entries are matched: forward slashes, no leading `./`, case-insensitive (Windows)."""
    text = path_text.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.casefold()


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def check_header(header: dict, machine_id=None, toolhead=None) -> list:
    """Machine-side checks of a v0.1 header (P3.2): problems, empty = fits. No header = v0 = nothing to check."""
    problems = []
    if header.get("machine") and header["machine"] != machine_id:
        problems.append(f"made for machine {header['machine']!r}, this is {machine_id!r}")
    if header.get("toolhead") and header["toolhead"] != toolhead:
        problems.append(f"made for toolhead {header['toolhead']!r}, detected {toolhead!r}")
    return problems


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
    return read_job(path).segments


def _header_line(header, rest, where):
    """One `JH key=value` line into `header`; returns a warning or None."""
    key, sep, value = rest.partition("=")
    key, value = key.strip().lower(), value.strip()
    if not sep or not key:
        raise JobError(f"{where}: header line must be 'JH key=value'")
    if key == "sha256":
        digest, _, file_text = value.partition(" ")
        digest, file_text = digest.lower(), file_text.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not file_text:
            raise JobError(f"{where}: expected 'JH sha256=<64 hex digits> <file>'")
        files = header.setdefault("sha256", {})
        if _key(file_text) in {_key(k) for k in files}:
            raise JobError(f"{where}: second sha256 for {file_text!r}")
        files[file_text] = digest
        return None
    if key in header:
        raise JobError(f"{where}: header key {key!r} given twice")
    header[key] = value
    return None if key in HEADER_KEYS else f"{where}: unknown header key {key!r} (ignored)"


def _check_file_header(header, where):
    version = header.get("jcode")
    if version is None:
        raise JobError(f"{where}: header without 'JH jcode=<version>'")
    try:
        major = int(version.split(".")[0])
    except ValueError as e:
        raise JobError(f"{where}: bad J-code version {version!r}") from e
    if major != SUPPORTED_MAJOR:
        raise JobError(f"{where}: J-code version {version} is not supported (reader: {SUPPORTED_MAJOR}.x)")
    if header.get("units", "mm").lower() != "mm":
        raise JobError(f"{where}: units {header['units']!r} are not supported (mm only)")


def read_job(path) -> JobFile:
    """Like read_job_file, with the v0.1 header (empty for v0 and `.nc`) and the header warnings."""
    path = Path(path)
    if path.suffix.lower() != ".jcode":
        return JobFile([read_gcode(path)])
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise JobError(f"cannot read J-code file {path}: {e}") from e
    segments, ref = [], (0.0, 0.0, 0.0, 0.0)
    header, warnings, checked_files = {}, [], set()
    body = False                                     # a J0 / J1 was read: no more header lines
    for number, raw in enumerate(lines, 1):
        line = strip_jcode_comment(raw)
        if not line:
            continue
        parts = line.split(None, 1)
        where = f"{path.name}:{number}"
        if parts[0].upper() == "JH":
            if body:
                raise JobError(f"{where}: header lines (JH) must come before the first J0 / J1")
            warning = _header_line(header, parts[1] if len(parts) > 1 else "", where)
            if warning:
                warnings.append(warning)
            continue
        if header and not body:
            _check_file_header(header, where)
        body = True
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
            written = parts[1].strip()
            target = Path(written)
            if header:
                # v0.1: the job folder is a package – it can be moved or archived as a whole
                if target.is_absolute() or target.drive or target.root:
                    raise JobError(f"{where}: absolute path in a J-code with header: {written!r} (use a relative path)")
                if not (path.parent / target).resolve().is_relative_to(path.parent.resolve()):
                    raise JobError(f"{where}: {written!r} is outside the job folder")
            if not target.is_absolute():
                target = path.parent / target
            if not target.exists():
                raise JobError(f"{path.name}:{number}: G-code file not found: {target}")
            if "sha256" in header:
                expected = {_key(k): v for k, v in header["sha256"].items()}.get(_key(written))
                if expected is None:
                    raise JobError(f"{where}: no sha256 in the header for {written!r}")
                if sha256_of(target) != expected:
                    raise JobError(f"{where}: {written!r} was changed after the job was made (sha256 mismatch)")
                checked_files.add(_key(written))
            segment = read_gcode(target)
            segment.ref = ref
            segments.append(segment)
        else:
            raise JobError(f"{path.name}:{number}: unknown J-code line {line!r}")
    if header and not body:
        _check_file_header(header, path.name)
    if not segments:
        raise JobError(f"{path.name}: no G-code segment (J1) in the file")
    unused = [k for k in header.get("sha256", {}) if _key(k) not in checked_files]
    if unused:
        raise JobError(f"{path.name}: sha256 in the header for files the job does not use: {', '.join(unused)}")
    return JobFile(segments, header, warnings)
