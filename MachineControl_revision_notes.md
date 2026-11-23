# Machine control revision – notes and rules

Carried over from the BildHatcher v2.0 revision. The target picture is `Ideas_v3.0.md` in the BildHatcher repo:
BildHatcher and the machine control become modules of one laser suite. Nothing about that integration is
decided yet; these rules only make sure the machine control does not drift away from it.

## Context from BildHatcher

The BildHatcher repo (local: `D:\Projekte\Coding\BildHatcher`, GitHub `goegilein/BildHatcher`, v2.0 on `main`)
is the reference for everything shared. Read these before deciding anything that touches it:

| File | Why |
|---|---|
| `Ideas_v3.0.md` | The target picture: suite of modules, PySide6, core package, machine control as its own process |
| `REVISION_PLAN.md` | How the v2.0 revision was run – use its structure for the plan here |
| `core/toolpath.py` | BildHatcher's tool-path model: `Layer` (one colour) with `speed`, `power` and polylines as arrays of rows (x, y, z, move) in mm, move = travel / burn / rapid. This is already close to the machine-neutral data of J-code – build on it |
| `core/machine.py`, `machine_profiles/*.json` | The machine profile format (G-code templates, feedrate, rapid speed, acceleration, over-drive fit, ...) to extend, not duplicate |
| `core/postprocess.py`, `core/gcode.py` | Today's machine-specific steps: lead-in / lead-out / over-drive and G-code generation for the Snapmaker |
| `Parsing.py` (`save_jcode`) | Today's J-code writer (`J0` reference position, `J1` file reference) |
| `theme.py`, `GUI_Files/styles/atelier.qss`, `GUI_Files/fonts`, `tools/apply_style.py` | The Atelier look (dark / bright), meant to be copied |
| `tests/test_characterization.py`, `tests/golden/` | How characterization ("golden") tests pin output before refactoring |

## First steps in the machine control repo

1. Read the code and write an inventory: modules, data flow, threads, how the machines are addressed today.
2. Collect bugs and risks (especially safety: what happens on errors, disconnects, exit).
3. Write `REVISION_PLAN.md` with phases, task IDs and the open questions below; agree on it with the user
   before changing code.
4. Phase 0: safety net – simulated machine, characterization tests of what is sent today, logging.
5. Only then refactor towards the rules below.

## Collaboration preferences (from the BildHatcher revision)

- Talk with the user in German; code, UI texts, commits and docs in English.
- Small, minimal changes; ask when a decision is the user's, otherwise pick the obvious option and say so.
- UI: layouts, icons, tooltips and sizes in the Designer .ui file, not built in code.
- Commit and push after every step with task IDs; keep the plan current in the same commit; merge into main
  only through a PR when the user says so.
- Put a short `CLAUDE.md` into the repo that points to this file and to `REVISION_PLAN.md`, so every session
  starts with them.

## Needed from the user (only you know this)

- Galvo machine: scanner card / controller and its SDK or list API, laser source and how it is triggered
  (power, frequency, timing), field size and correction, own hardware modules and their interfaces.
- Marlin machine: model, firmware version, serial settings, which parts are your own hardware and how they are
  addressed (own M-codes?).
- Today's pain points and bugs of the machine control, and what must keep working during the revision.
- Priorities: which machine first, what is needed for production soon.

## Machines

- **Own machine** (built and programmed by us) with a **galvo scanner** – works with scanner lists, not with
  classic G-code. Its architecture goes beyond a G-code interface.
- **Manufacturer machine** with **Marlin G-code over a serial port**; only some hardware modules are our own.
- Both have to be operated from the suite.

## J-code: the job format (user's plan, 2026-11-22)

All instructions are stored as **files in one clearly defined format – "J-code"**: close to G-code, but one level
above it. A J-code file describes the sequence and references single segments – G-code segments, own commands,
or whole scanner lists in separate files. The machine control of each machine loads it; an integrated module
may hand over the path or the content directly.

Why: one defined format; compute in advance and edit later; compute for another machine and process the same
product there; above all **store recipes and repeat them any number of times** (traceability).

Today's state in BildHatcher (`Parsing.save_jcode`): `J0 X Y Z R` sets the reference position of a cluster,
`J1 <file>` references a G-code file (absolute path), one `.nc` file per hatch cluster.

### Decided (2026-11-23)

- **Neutral data is always stored.** BildHatcher (and every other producer) always writes the machine-neutral
  segments (geometry in mm + process parameters) into the job. This is the master copy of a recipe / job.
- **Machine-specific code is optional, in addition.** BildHatcher can also output code for a target machine
  (e.g. Marlin G-code with lead-in / lead-out, later scanner lists), marked with the target machine / profile
  and the checksum of the neutral data it was computed from.
- **The machine control accepts both.** It uses the machine-specific code if it is meant for this machine and
  profile and still matches the neutral data (checksum); otherwise it translates the neutral data with its own
  driver. A job without neutral data is still runnable (e.g. hand-written G-code), but cannot be moved to
  another machine.

### Proposals to discuss (Claude)

1. *(decided, see above)* **Machine-neutral geometry as the primary content.** A G-code segment already contains machine knowledge
   (acceleration, lead-in / lead-out, over-drive) and is useless on the galvo (jump / mark speed, laser delays,
   field correction). Segments should therefore be neutral – polylines in mm plus process parameters (power,
   speed, frequency, passes) – and each machine's driver translates them (Marlin → G-code, galvo → scanner
   list). Machine-specific segments (own G-code, scanner lists) stay possible but are marked with their target
   machine. Precomputed machine code may sit next to them as a cache, with the checksum of its source.
2. **A package instead of loose files with absolute paths:** a folder or ZIP container (like .3mf / .docx) with
   a manifest and the segments, referenced by relative paths – one unit to copy, archive and move to another
   machine.
3. **Versioned specification and header:** format version, units, coordinate system, creator and time,
   references to machine and material profiles, checksums (SHA-256) of all linked files – without checksums a
   recipe is not really reproducible.
4. **Separate recipe, job and run:** *recipe* = reusable parameter set for a material / colour; *job* = a recipe
   applied to a motif at a position; *run log* = every execution (job + checksum, machine, time, result). The run
   log is the actual traceability.
5. **Capabilities in the machine profile** (work area, rotary axis, power range, supported segment types); every
   machine control validates a job against them before it starts and refuses it otherwise.
6. **One shared library for the format** (parser, writer, validator) with its own spec and tests, ideally its
   own repo – used by BildHatcher and both machine controls, so there is only one reading of the format.
7. Keep the G-code-like line syntax for the sequence (readable, streamable); put the metadata into a structured
   header or manifest (easier and safer to parse than comments).

## How we work

- **Revision plan in the repo.** One `REVISION_PLAN.md` at the root: status table per phase, task IDs
  (bugs `B..`, plan items `P..`), decisions, open questions, work log. It is updated in the same commit as the
  work, so it is current on every machine.
- **Own branch, task IDs in commits, push after every step.** Main is only merged when the user decides,
  through a PR.
- **Safety net before refactoring.** First characterization tests that pin today's behaviour (e.g. the exact
  bytes / G-code sent for a recorded job), then change the code. Intended output changes are documented in the
  plan and the reference files are regenerated on purpose.
- **Small, minimal changes.** The simplest thing that works; no speculative abstractions ("ponytail").
- **Verify in the real app**, not only in tests: screenshots for UI changes, a simulator run for protocol changes.

## Architecture rules (towards v3.0)

1. **Core without Qt.** Connection, protocol, streaming, job queue and the machine state live in plain Python
   modules that import no Qt. The UI only displays state and sends commands. This core becomes the installable
   package later.
2. **Never in the UI thread.** Communication with the machine runs in its own thread now, and must be movable to
   its own process later. The UI must never block the machine and the machine must never block the UI.
3. **Message interface instead of direct calls.** Commands (connect, home, jog, start job, pause, resume, stop,
   emergency stop) and events (state, position, progress, errors, log lines) are plain data – dataclasses that
   serialize to JSON. Then the transport (Qt signals today, IPC / ZeroMQ / WebSocket later) can be swapped
   without touching either side.
4. **Explicit state machine.** States such as disconnected, connecting, idle, running, paused, error,
   emergency stop – with defined transitions. No state hidden in widget flags.
5. **Jobs come as J-code.** The machine control executes J-code jobs (from a file, or handed over in memory by an
   integrated module – same model); it does not create hatching itself. It runs precomputed machine code when
   it matches (target, profile, checksum) and otherwise translates the neutral segments with its driver (one
   driver per machine: Marlin G-code, galvo scanner lists). The translation of neutral data into machine code
   lives in one shared place, used by BildHatcher's optional export and by the machine controls alike.
6. **One machine profile format.** BildHatcher has `machine_profiles/*.json` (G-code templates, `rapid_speed`,
   `acceleration`, `over_drive_fit`, ...). Extend that format instead of creating a second one; who owns the
   profiles in the suite is an open question.
7. **Ready for PySide6.** Qt imports only in the UI layer; no PyQt-only API in new code (or behind a small
   alias such as `Signal = pyqtSignal`), so the later switch stays mechanical.
8. **Same look.** Reuse the Atelier style from BildHatcher (`theme.py`, `GUI_Files/styles/atelier.qss`,
   `GUI_Files/fonts`, dark / bright) instead of a new stylesheet. Layouts, icons, tooltips and sizes belong
   in the .ui file so Qt Designer shows the real look.

## Safety rules

- **Emergency stop has the shortest path:** independent of the job queue and the stream buffer, available in
  every state, and also reachable by hotkey.
- **Laser off on everything unexpected:** error, lost connection, timeout, app exit, exception in the stream
  thread.
- **Never resume automatically** after an error or reconnect – the user decides.
- **Check before sending:** job within the work area of the profile, power and speed within its limits, a valid
  profile selected. Refuse the job otherwise, with a clear message.
- **Acknowledged streaming with timeouts and a watchdog;** a missing acknowledgement stops the job safely
  instead of hanging.

## Testing and diagnosis

- **Simulated machine** (a fake serial port / network endpoint that answers like the real firmware) so all
  tests run without hardware. Use recorded logs of the real machine as reference conversations.
- **Hardware tests** are separate and manual, with a short checklist (connect, home, frame, short job, pause /
  resume, stop, emergency stop, cable pulled during a job).
- **Protocol log:** every command sent and every answer received, with timestamps, in a rotating log file in
  the user folder – the first thing to look at when something goes wrong.

## Conventions

- English for UI texts, code and docs; type hints on everything that crosses module boundaries.
- README with a table of modules and their responsibility, kept current.
- User data (settings, logs, profiles) in the user folder, never next to the program.

## Questions to answer during the rework (feed back into Ideas_v3.0.md)

- Which parts of the existing machine control already fit the rules above, which need a rewrite?
- What exactly does each machine need (Marlin: protocol, acknowledgements, buffer size, status queries; galvo:
  scanner card / list API, laser timing, field correction)?
- J-code spec: commands, header / manifest, segment types (neutral vs machine-specific), package layout,
  versioning – and where the shared library lives.
- Who owns machine profiles and material / colour profiles in the suite?
