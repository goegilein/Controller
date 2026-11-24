# J-code specification

J-code is the job format of the machine suite: a short sequence file that places and orders **segments** (today
G-code files). This document describes:

- **v0**: what BildHatcher writes today and what Machine Control 2.0 reads (binding);
- **v0.1**: the optional header (draft, REVISION_PLAN.md P3.2).

The reader is `machine_core/jcode.py`, and the tests are in `tests/test_jcode.py`.

---

## 1. v0 (binding)

### 1.1 File

- Text file in UTF-8 with the extension `.jcode`, one command per line. Blank lines are ignored.
- **Comments** start with `;` and run to the end of the line. Parentheses are **not** comments in a J-code file,
  so a file name such as `job (1).nc` is valid.
- Command words are case-insensitive.

### 1.2 Commands

| Command | Meaning |
|---|---|
| `J0 X<x> Y<y> Z<z> R<r>` | Reference position of the following segments, in mm and degrees, relative to the process step. A missing word means 0, not the previous value. Only the words `X Y Z R` are allowed. |
| `J1 <file>` | Run one G-code segment at the current reference position. `<file>` is the rest of the line without the comment. A relative path is resolved against the folder of the J-code file. |

Any other line is an error.

A job runs its segments in file order. A `.nc` file given directly instead of a J-code is one segment at
`J0 X0 Y0 Z0 R0`.

### 1.3 Where a segment burns

The machine runs everything in **absolute machine coordinates** (no `G92`). For segment point `p` in step `s`:

```
machine = T_laser · T_step(s) · Trans(J0 X, Y, Z) · p
```

- `T_step` is the process step's position and its part rotation about Z (from a stored position, P2.6).
- `T_laser` is the laser offset of the detected toolhead, a pure translation in machine coordinates.
- `J0 R` is added to the step's rotary base angle and turns the rotary stage. The stage turns only while the head
  stands still, after `M400`.

### 1.4 G-code segments

- Units are mm. `G21` is accepted, `G20` (inch) is refused.
- `G0` and `G1` with `X Y Z` and other words (`F S P ...`) are kept in their original order. `G90` and `G91` are
  resolved into absolute targets.
- Every other `G`, `M` or `T` command is sent unchanged, for example `M3 / M4 / M5`, `M8 / M9`, `G4` and `M2000`.
- These commands are **refused when the job is loaded**: `G2 G3` (arcs), `G20`, `G28` (homing),
  `G92` (coordinate shift) and `G53`–`G59` (work offsets).
- Comments are `( ... )` and everything after `;`. A line that is not a command, such as BildHatcher's
  `===;start of new Processblock===`, is skipped with a warning.
- Long moves are split into pieces of at most 1 s, so that pause reacts quickly and the progress display is
  smooth.

### 1.5 Checks before the job starts

The job is refused before anything moves if any of these holds:

- a file is missing or a line is invalid;
- the machine is not homed or the toolhead is unknown;
- a move leaves the work area;
- power is outside `S` 0..255 or `P` 0..100;
- the feed is not allowed;
- a step needs a rotary stage that is not assigned.

The checks are in REVISION_PLAN.md, P2.5.

### 1.6 What BildHatcher writes today (2.x)

```
; This file was created by BildHatcher
; Created: 2026-11-24 10:00:00

J0 X12.5 Y-3 Z0 R0
J1 C:\jobs\motif_block-1_cluster-1.nc
J0 X40 Y-3 Z0 R90
J1 C:\jobs\motif_block-1_cluster-2.nc
```

It writes absolute paths, all four `J0` words and one G-code file per hatch cluster, with the machine profile's
header and footer inside each file.

---

## 2. v0.1 header (draft – to be decided)

The header carries metadata (format version, target machine and toolhead, checksums), so the machine can check
that a job fits it and is still the file that was produced (decision 2026-11-24 (3)). BildHatcher keeps writing
v0 until v3.0. The controller accepts both: a J-code without a header runs as v0.

### 2.1 Proposed syntax

A structured header instead of comments (revision notes, proposal 7). One `JH` line holds a JSON object and must
be the first command in the file:

```
; This file was created by BildHatcher
JH {"jcode": "0.1", "creator": "BildHatcher 3.0.0", "created": "2026-11-24T10:00:00", "units": "mm", "machine": "snapmaker_artisan", "toolhead": "laser455", "files": {"motif_block-1_cluster-1.nc": "sha256:9f2c…", "motif_block-1_cluster-2.nc": "sha256:41ab…"}}
J0 X12.5 Y-3 Z0 R0
J1 motif_block-1_cluster-1.nc
```

| Key | Required | Meaning | Check by the machine control |
|---|---|---|---|
| `jcode` | yes | format version | unknown major version → refuse |
| `creator`, `created` | no | producer and time | logged only |
| `units` | no (default `mm`) | units | anything else than `mm` → refuse |
| `machine` | no | machine profile id (C10) | another machine → refuse |
| `toolhead` | no | toolhead the job was made for | not the detected head → refuse |
| `files` | no | SHA-256 per `J1` file, keyed by the path as written in `J1` | mismatch or missing file → refuse |

Open points for the decision:

- Refuse or only warn on a mismatch? The proposal refuses. A changed file or the wrong head is exactly what the
  check is for.
- One `JH` JSON line, or several `JH key=value` lines (easier to read and edit by hand)?
- Relative `J1` paths become the rule once a header is present, so a job folder can be moved (revision notes,
  proposal 2: a package).
