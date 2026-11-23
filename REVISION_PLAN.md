# Machine Control – Code Revision 2.0

Living plan for the revision of the machine control. Work happens on branch **`revision_2.0`** (from `main`).
This file is the single source of truth for status – update it in the same commit as the work it describes.

- Rules and background: [MachineControl_revision_notes.md](MachineControl_revision_notes.md). Reference for
  everything shared: BildHatcher (`D:\Projekte\Coding\BildHatcher`, v2.0 on `main`). New machine:
  `D:\Projekte\Coding\LaserMachine` (Nur_Gantry.md, Kap. 8).
- Baseline commit: `3605785` (main). All `file:line` references refer to that commit and will drift.
- Status markers: `[ ]` open · `[~]` in progress · `[x]` done · `[-]` dropped (give reason).
- Task IDs are stable (`B07`, `P2.3`); reference them in commit messages, e.g. `B07: stop rotary motors on exit`.
- **The Snapmaker Artisan is in production.** Every change that alters what is sent to the machine is listed in
  section 5 and agreed with the user before it is made.

---

## Current status

| Phase | State | Notes |
|---|---|---|
| Inventory & plan | **draft – waiting for the user** | open questions in section 6 |
| 0 – Safety net | open | protocol log first, so real conversations can be recorded |
| 1 – Safety fixes in the existing code | open | only what production needs now |
| 2 – Machine core without Qt (Marlin) | open | |
| 3 – J-code and machine profile | open | prepare v3.0, no galvo driver yet |
| 4 – UI, user data, conventions | open | |
| 5 – Release 2.0.0 | open | hardware checklist, PR to main |

---

## 1. Goals

- **The Artisan keeps working** at every commit that is pushed; behaviour changes are explicit and agreed.
- **Safe:** laser off on everything unexpected, an emergency stop that always works, no automatic resume,
  missing acknowledgements stop the job.
- **Core without Qt, communication never in the UI thread, message interface, explicit state machine**
  (architecture rules 1–4 of the notes) – the core becomes the installable machine-control package of v3.0.
- **Ready for v3.0:** J-code as the job format, one machine-profile format shared with BildHatcher, a driver
  boundary that the galvo machine can use later.

---

## 2. Inventory (baseline `3605785`)

### 2.1 Modules

| Module | Lines | Responsibility | Qt? |
|---|---|---|---|
| [main_Controller.py](main_Controller.py) | 81 | wires everything up at module level, no `main()` | yes |
| [Artisan_Controller.py](Artisan_Controller.py) | 612 | serial / TCP connection, `send_command`, jog, moves, G92 work position, M114 tracking thread, toolhead detection (M1006), enclosure light / fan / air / crosshair | `QMessageBox` in `connect()` |
| [Artisan_GUI_Interface.py](Artisan_GUI_Interface.py) | 231 | jog buttons, speed / step, position display, toggles | yes |
| [Process_Handler.py](Process_Handler.py) | 738 | process steps, job thread, pause / resume / cancel, bounding box, `NCCodeInterpreter` (G-code / J-code reader, segmentation of long moves, time estimate) | no (numpy only) |
| [Process_GUI_Interface.py](Process_GUI_Interface.py) | 348 | process-step list widgets, start / pause / cancel, bounding-box UI | yes |
| [RotMotor_Cotroller.py](RotMotor_Cotroller.py) | 437 | STS servos via `libraries/scservo_sdk`, wheel mode, **PID loop on the PC at 50 Hz** | no |
| [RotMotor_GUI_Interface.py](RotMotor_GUI_Interface.py) | 121 | rotary-motor widgets | yes |
| [Camera_Controller.py](Camera_Controller.py) | 132 | OpenCV capture driven by a `QTimer` in the UI thread | `QTimer` |
| [Camera_GUI_Interface.py](Camera_GUI_Interface.py) | 390 | camera view, image save, laser-cross detection (WIP) | yes |
| [Interactive_Image_Control.py](Interactive_Image_Control.py) | 498 | click-to-move in the camera image, homography calibration | yes |
| [Maschine_Helper.py](Maschine_Helper.py) | 1070 | circle / rectangle fit, custom sample holders (3-point transform), stored positions (JSON) | yes |
| [Gcode_Plotter.py](Gcode_Plotter.py) | 115 | 3D preview (pyqtgraph / OpenGL) | yes |
| [Settings_Manager.py](Settings_Manager.py), [Settings_Binder.py](Settings_Binder.py) | 194, 348 | layered JSON settings with Qt signals, settings editor | yes |
| [ArduinoController.py](ArduinoController.py) | 194 | joystick / keypad / IR remote – **commented out in main** | no |
| [PathManager.py](PathManager.py), [build_executable.py](build_executable.py) | 96, 205 | paths (frozen / source), PyInstaller build with version bump | no |
| [BaseClasses.py](BaseClasses.py), [Custom_UIs.py](Custom_UIs.py) | 81, 17 | widget helpers, `SignalEmitter`, `TextLogger` | yes |

### 2.2 How the Artisan is addressed today

- **Transport:** USB serial (`pyserial`, 115200, timeout 1 s); a TCP path exists but is untested (`recv(1024)` is
  not line based, `tcp_port` is the string `"None"` in the settings).
- **Protocol:** ping-pong. `send_command` writes one line and reads lines until one *contains* `wait_text`
  (default `"ok"`, timeout 60 s), all under one lock (`comand_lock`). No line numbers / checksums, no handling of
  `Error:` / `Resend:` / `busy:`.
- **Commands in use:** `G0/G1`, `G90/G91`, `G92 X0 Y0 Z0` (work position), `G28`, `M114` (position), `M400` +
  `M118 <text>` (sync point), `M1006` (toolhead info), `M2000 L13` (crosshair), `M2000 W1/W2` (light / fan),
  `M8/M9` (air assist), `M112` (emergency stop, not wired to the UI).
- **Coordinates:** the app keeps `origin_offset` (sum of all G92 shifts since homing) to show "absolute"
  positions; stored positions, process-step work positions and fit points are in these absolute coordinates.
  Work positions are camera / crosshair positions; the job adds the laser offset of the detected toolhead.
- **Job execution** ([Process_Handler.py:211](Process_Handler.py#L211)): for every step: move Z-safe to the work
  position (+ rotary angle), move by the laser offset, `G92`; for every `J0`: absolute move to
  `J0 + work position + laser offset`, `G92`, rotary move, sleep 0.5 s; for every `J1`: stream the G-code lines
  (long moves split into ≤ 1 s segments), then `M400` + `M118 step_<n>_done`. At the end: back to the start
  position and `G92` there.

### 2.3 Threads

| Thread | Started in | Does |
|---|---|---|
| UI | – | **most serial I/O**: jog steps, absolute / relative moves, homing (`G28`, up to 60 s), set work position, toggles, bounding box, `get_absolute_position` for fit points |
| position tracking | `connect()` [Artisan_Controller.py:146](Artisan_Controller.py#L146) | `M114` every 0.1 s unless the state is `Running`; one more thread per connect |
| continuous jog | `move_axis_continuous` | `G91`, `G0` increments every 0.1 s while a button is held, `G90` (not a daemon) |
| job | `start_process` | the whole job; calls controller methods with `job_save=True` |
| rotary control | `RotMotorCotroller.start_control_loop` | reads positions and writes wheel speeds at 50 Hz |
| camera | – | `QTimer` in the UI thread, `cv2.read()` blocks the UI |

### 2.4 What already fits the rules

- `NCCodeInterpreter`, the rotary PID (`RotMotor`) and the fit maths in `Maschine_Helper` are plain Python –
  they move into the core almost unchanged.
- `TextLogger` already uses a signal to log from threads; `PathManager` already separates bundled and external files.
- The job is already J-code based (`J0` reference position incl. `R`, `J1` G-code segment) – the same format
  BildHatcher writes (`Parsing.save_jcode`).

---

## 3. Bugs and risks

Severity: **S** = safety (person, machine, workpiece), **F** = wrong function, **M** = maintenance.
"Fix in" names the phase; `P1` = small fix in the existing code because production needs it before the new core.

| ID | Sev | Finding | Where | Fix in | State |
|---|---|---|---|---|---|
| B01 | S | **Laser is never switched off on cancel, error or app exit.** The job only sends `M5` if the G-code footer is reached. Cancel, an exception in the job thread or closing the window (daemon thread killed) leave the laser mode / power active; in `M3` (constant) mode the laser may keep firing at standstill. | [Process_Handler.py:236-246](Process_Handler.py#L236-L246), no `closeEvent` | P1 | open |
| B02 | S | **A missing acknowledgement does not stop the job.** `_read_until` only logs on timeout; `send_command` swallows every exception. A lost USB connection makes the job "run" through all remaining lines, logging errors. | [Artisan_Controller.py:190-250](Artisan_Controller.py#L190-L250) | P2 | open |
| B03 | F | **Acknowledgements are off by one after every `M114`.** `M114` waits for `"X:"`, its `ok` stays in the buffer and is consumed by the next command (the "do it twice" workaround for `M1006` is caused by this). In practice the job runs with up to 2 lines in flight. Fixing it changes the streaming timing → see C3. | [Artisan_Controller.py:432](Artisan_Controller.py#L432), [:579](Artisan_Controller.py#L579) | P2 | open |
| B04 | S | **Emergency stop is not reachable.** `emergency_stop()` is not wired to any button or hotkey (`stop_axis_button` in the .ui is unused). If it were: `M112` waits for the command lock (held up to 60 s by the job thread) and then 60 s for an `ok` that never comes. | [Artisan_Controller.py:510](Artisan_Controller.py#L510) | P1 | open |
| B05 | S | **Jogging during pause, then resume, burns a line.** Move controls are enabled in `Paused`; after resume the next `G1` starts from the jogged position. | [Artisan_GUI_Interface.py:194-196](Artisan_GUI_Interface.py#L194-L196) | P1 | open |
| B06 | S | **Rotary motors can keep spinning.** Wheel mode with a PC-side PID: if the control thread dies (the dummy `read_pos(0)` is outside the `try`), the app exits or `disconnect()` closes the port, the last speed stays active. `move_to_angle(wait_for_position=True)` waits forever (the 100 s timeout is unused) → job hangs. | [RotMotor_Cotroller.py:114-180](RotMotor_Cotroller.py#L114-L180) | P1 | open |
| B07 | S | **Widgets are changed from worker threads.** `Artisan_GUI_Interface.threadsafe_update_process_state` calls the update directly (the emitter is unused); `ProcessInterface.update_process_state` is registered as a plain callback and runs in the job thread. Can crash Qt during a job. | [Artisan_GUI_Interface.py:186-189](Artisan_GUI_Interface.py#L186-L189), [Process_GUI_Interface.py:44](Process_GUI_Interface.py#L44) | P1 | open |
| B08 | S | **No checks before the job:** work area, power / speed limits, a known toolhead / laser offset. `get_toolhead_info` returns `"TEST"` if the machine does not answer, so a job can start with `laser_offset = None` (fails mid-way). Unknown toolhead is detected by the *number* of `M1006` lines (39 / 34). | [Artisan_Controller.py:568-612](Artisan_Controller.py#L568-L612), [Process_Handler.py:261](Process_Handler.py#L261) | P2 (`"TEST"` in P1) | open |
| B09 | F | A missing G-code file of a J-code is only printed and skipped; the `J1` indices then point to the wrong / no segment → `IndexError` mid-job, the rest of the step is skipped, **the next step still runs**. `J1` paths are resolved against the working directory, not the J-code folder. | [Process_Handler.py:578-579](Process_Handler.py#L578-L579) | P2 | open |
| B10 | F | Bounding box in laser coordinates **adds the laser offset to the step's stored box every time** it is run. It also leaves a `G92` at the work position and runs in the UI thread. | [Process_Handler.py:409-442](Process_Handler.py#L409-L442) | P2 | open |
| B11 | S | `G91 … G90` sequences are not atomic: a continuous jog (own thread, `G91`) and an absolute move from the UI (`G90`) can interleave → a jog increment executed as an absolute target. | [Artisan_Controller.py:252-290](Artisan_Controller.py#L252-L290) | P2 | open |
| B12 | F | Serial I/O in the UI thread: homing blocks the UI up to 60 s, every move / fit-point capture blocks; `disconnect()` sleeps 1.5 s. | many | P2 | open |
| B13 | F | Position tracking dies on the first failed `M114` (`current_position = None` → `TypeError` in the setter) and is not restarted; every reconnect starts another tracking thread. | [Artisan_Controller.py:146-157](Artisan_Controller.py#L146-L157) | P2 | open |
| B14 | F | `cancel_process` joins the job thread in the UI thread (UI frozen during the move back); called from the job thread itself on a failed sync it raises `cannot join current thread`. Cancel is refused when disconnected. | [Process_Handler.py:385-401](Process_Handler.py#L385-L401), [:358](Process_Handler.py#L358) | P2 | open |
| B15 | F | `origin_offset` / `is_homed` live only in the app: after a reconnect without homing (or an app crash) the machine still has the old `G92` shift, the app assumes none → all "absolute" positions (stored points, work positions) are wrong. | [Artisan_Controller.py:456-473](Artisan_Controller.py#L456-L473) | P2 | open |
| B16 | F | A settings change calls `get_toolhead_info` (`M1006` twice) – also during a running job. Typo `artisan.motoin.max_z_speed` (always the fallback 30). `move_axis_to` / `move_axis_absolute` clamp X/Y speed to the Z limit too. | [Artisan_Controller.py:96-108](Artisan_Controller.py#L96-L108), [:344](Artisan_Controller.py#L344) | P2 | open |
| B17 | F | Default work position `[1, 400, 400, 0]` when the position is unknown. `J0` without `Z` / `R` reuses stale values or raises `NameError`. | [Process_Handler.py:83](Process_Handler.py#L83), [:307-318](Process_Handler.py#L307-L318) | P2 | open |
| B18 | F | After the job the work position is set to the *start* position, not restored to the user's previous one (intended? → C6). | [Process_Handler.py:237-238](Process_Handler.py#L237-L238) | P2 | open |
| B19 | M | Icons loaded by relative path (`QIcon("GUI_files/resources/pause.png")`) – break in the built exe or another working directory. | [Process_GUI_Interface.py:294-304](Process_GUI_Interface.py#L294-L304) | P4 | open |
| B20 | M | 26 `__pycache__/*.pyc` files are tracked despite `.gitignore`. | repo | P0 | done |
| B21 | M | User data (settings, stored positions, homographies) is written next to the program, not into the user folder. | [PathManager.py](PathManager.py) | P4 | open |
| B22 | M | Rotary `connect()` reports "connected" even if `openPort()` fails; gear ratio 3 hard-coded (LaserMachine spec says 4:1 today). | [RotMotor_Cotroller.py:61-112](RotMotor_Cotroller.py#L61-L112), [:279](RotMotor_Cotroller.py#L279) | P2 | open |
| B24 | F | Comment stripping only cuts at `;`: BildHatcher's line `===;start of new Processblock===` is sent to the machine as `===` (Marlin answers "Unknown command" + `ok`). Parentheses comments are not handled. | [Process_Handler.py:555-563](Process_Handler.py#L555-L563) | P2 | open |
| B23 | M | Remaining-time estimate uses a fudge factor 2; long-move segmentation and the estimate ignore acceleration and `G2/G3`. | [Process_Handler.py:354](Process_Handler.py#L354) | P3 | open |

---

## 4. Target architecture (v2.0, prepared for v3.0)

```
machine_core/            plain Python, no Qt – becomes the installable package in v3.0
  messages.py            Command / Event dataclasses, to_json / from_json
  state.py               MachineState + allowed transitions
  transport.py           SerialTransport, SimTransport (fake Snapmaker Marlin for tests)
  marlin.py              line protocol: reader thread, ack matching, Error / busy, timeouts, watchdog
  worker.py              one thread owns the port: command queue, emergency-stop bypass, events out
  jcode.py               today's J-code reader (+ header, see P3), job model, preflight checks
  stages.py              rotary stages (from RotMotor_Cotroller) with safe stop
  protocol_log.py        rotating log of every line sent / received, user folder
ui/ (existing modules)   only display state and send commands; one QtBridge turns events into signals
```

- **One thread owns the serial port.** The UI and the job runner put commands into its queue; nothing else
  touches the port. Emergency stop is written by the worker *before* anything queued, and does not wait for an ack.
- **States:** `disconnected → connecting → idle ⇄ jogging / homing`, `idle → running ⇄ paused`, any → `error`,
  any → `estop`. Leaving `error` / `estop` needs a user action; nothing resumes automatically.
- **Laser-off rule in one place:** on cancel, error, lost connection, ack timeout, exception in a worker thread
  and app exit, the worker sends the laser-off sequence of the profile (Artisan: `M5`, then `M9`) if the port
  is still alive.
- **Driver boundary:** the job runner talks to a driver (`MarlinDriver` now). The galvo machine (LinuxCNC Python
  API + own galvo controller + ESP32 stages, LaserMachine Kap. 8) gets its own driver in v3.0 – not built now.
- Qt stays PyQt6 for v2.0; Qt is imported only in the UI layer, signals via `Signal = pyqtSignal` alias.

---

## 5. Phases

### Phase 0 – Safety net

- [x] P0.1 `CLAUDE.md`, this plan, untrack `__pycache__` (B20), `requirements.txt` pinned to the versions of the
  build machine (Python 3.14).
- [x] P0.2 **Protocol log** ([protocol_log.py](protocol_log.py)) in the existing `send_command` / `_read_until` /
  `get_response`: every line sent and received with timestamp and thread, notes for connect / timeouts / exceptions,
  rotary-motor targets and stops; `%USERPROFILE%\Documents\MachineControl\logs\protocol.log` (20 MB × 10).
  *No change to what is sent.* Lets us record real conversations
  of the Artisan (connect, M114, M1006 per toolhead, homing, short job, pause, cancel).
- [ ] P0.3 **Simulated Artisan**: a fake serial port that answers like the recorded firmware (`ok`, `M114`
  format, `M1006` lines, `M118` echo, `M400` delay, `busy:`).
- [ ] P0.4 **Characterization tests** (golden files): for recorded J-code / G-code jobs, the exact sequence of
  lines the current code sends (incl. `G91/G90`, `G92`, segmentation, sync points), plus `NCCodeInterpreter`
  output (segments, times, bounding box). `python -m pytest`, no hardware.
- [ ] P0.5 Manual hardware checklist (connect, home, jog, set WP, frame, short job, pause / resume, cancel,
  emergency stop, cable pulled during a job, rotary stage move) – run before every merge.

### Phase 1 – Safety fixes in the existing code (each one agreed, tested on the machine)

- [ ] P1.1 B01 laser off (`M5`, `M9`) on cancel, on exception in the job thread and in a `closeEvent` / `aboutToQuit`.
- [ ] P1.2 B04 emergency-stop button + hotkey; `M112` written directly to the port, bypassing the lock, no ack wait.
- [ ] P1.3 B05 move controls stay disabled in `Paused` (or see C4).
- [ ] P1.4 B06 rotary motors: speed 0 on disconnect / exit / control-loop exception, timeout in `move_to_angle`.
- [ ] P1.5 B07 process-state updates to widgets through signals.
- [ ] P1.6 B08 part: refuse to start a job without a detected toolhead (remove the `"TEST"` return).

### Phase 2 – Machine core without Qt (Marlin)

- [ ] P2.1 `messages.py`, `state.py` with tests.
- [ ] P2.2 `transport.py`, `marlin.py`: line reader, ack matching (fixes B03), `Error:` handling, timeouts and a
  watchdog that stop the job safely (B02); in-flight window as decided in C3.
- [ ] P2.3 `worker.py`: single owner of the port, atomic command sequences (B11), emergency-stop bypass, tracking
  by `M114` polling in the worker (B13), no serial I/O in the UI (B12).
- [ ] P2.4 Job runner on the worker: today's J-code semantics, pause / resume / cancel per C4, fails at load time
  on missing files (B09), relative `J1` paths, no joins in the UI (B14), work position per C6 (B18).
- [ ] P2.5 Preflight checks: work area, toolhead / laser offset known, files present, rotary motor assigned,
  power / speed within the profile (B08, B17).
- [ ] P2.6 Coordinates: decide G92 vs work coordinate systems (C5) and make the absolute position survive
  reconnects (B15).
- [ ] P2.7 `stages.py` from `RotMotor_Cotroller` with safe stop and timeouts; direction per C8.
- [ ] P2.8 QtBridge; switch `Artisan_GUI_Interface`, `Process_GUI_Interface`, `Maschine_Helper`,
  `Interactive_Image_Control` to commands / events. Characterization tests updated **only** for agreed changes.

### Phase 3 – J-code and machine profile (prepare v3.0)

- [ ] P3.1 Write down today's J-code as spec v0 (`J0 X Y Z R`, `J1 <file>`, comments) – the reader stays compatible.
- [ ] P3.2 Optional header / manifest (format version, creator, target machine / profile, SHA-256 of linked files)
  read and checked if present – coordinated with BildHatcher.
- [ ] P3.3 Machine profile: read BildHatcher's `machine_profiles/*.json` format and extend it with capabilities
  (work area, power / speed range, toolheads with laser offset, rotary axis, laser-off sequence) instead of the
  `artisan.*` settings. Where the profiles live → C10.
- [ ] P3.4 Run log (job + checksum, machine, profile, time, result) – first step of traceability.
- [-] Neutral segments → machine code in the machine control: needs the shared library (notes, proposal 6);
  stays in BildHatcher until v3.0.

### Phase 4 – UI, user data, conventions

- [ ] P4.1 User data into the user folder with a one-time migration of the existing `settings/*.json` (B21, C9).
- [ ] P4.2 Atelier style from BildHatcher (dark / bright); inline styles and sizes into the .ui files; icons via
  `PathManager` (B19).
- [ ] P4.3 README with module table; `main()` instead of module-level wiring.

### Phase 5 – Release 2.0.0

- [ ] P5.1 Hardware checklist (P0.5) passed on the Artisan, results in the work log.
- [ ] P5.2 Version 2.0.0, build script checked, PR to `main` when the user decides.

---

## 6. Open questions / to decide with the user

| ID | Question | Proposal |
|---|---|---|
| C1 | Snapmaker firmware version, connection (USB only? is TCP used?), own hardware modules / M-codes besides rotary stages and cameras? | drop TCP if unused |
| C2 | Is there a physical emergency stop on the Artisan? Software: `M112` (firmware halt, machine needs a restart) as E-stop, plus a soft "Stop" (`M410` quick stop + `M5`, keeps the connection)? | both, E-stop also by hotkey |
| C3 | Streaming: today effectively 2 lines in flight (side effect of B03). Pure ping-pong after the fix could starve the planner on short hatch segments → slower, different burn result. | keep a fixed window of 2 lines intentionally, configurable, compare a test burn |
| C4 | Pause: laser off (`M5`) during pause and restore mode / power on resume? Jogging during pause allowed (then return to the pause position with laser off before resuming)? | laser off in pause; no jogging in pause for 2.0 |
| C5 | Work position via `G92` + app-side offset (today) vs `G54…` / `G53` (if the Snapmaker firmware supports them) | test what the firmware supports, then decide |
| C6 | After a job: set the work position to the start position (today) or restore the previous one? | restore the previous one |
| C7 | Toolhead detection by `M1006` line count – firmware updates could break it. Is there a field in the answer that identifies 1064 nm / 455 nm? | need a recorded `M1006` of both heads |
| C8 | Rotary stages: keep the PC-side PID for 2.0 (with safety fixes) or move the loop into the ESP32 firmware now (protocol `MOVE / DONE / heartbeat` as planned in LaserMachine Kap. 8.7 – the same stages will be used on the new machine)? Gear ratio 3 or 4? | PC PID + fixes in 2.0; ESP32 firmware as a separate step |
| C9 | Production uses the built exe with `settings/` next to it – OK to move to `%USERPROFILE%\Documents\…` with migration? | yes, like BildHatcher |
| C10 | Who owns machine profiles in the suite (BildHatcher, machine control, shared package)? | shared package in v3.0; for 2.0 a copy of the format |
| C11 | Arduino joystick / keypad (commented out), camera autofocus (WIP): keep, freeze or remove? | freeze, not in scope |
| C12 | Priorities: what is needed for production soon, and which hardware tests / log recordings can you do when? | – |

---

## 7. Decisions

| Date | Decision |
|---|---|
| 2026-11-23 | Branch `revision_2.0` created from `main` (`3605785`, contains `stored_pos`). |

---

## 8. Work log

| Date | What | Commit |
|---|---|---|
| 2026-11-23 | Inventory, bug list, phase plan (draft) | `fbb214b` |
| 2026-11-23 | P0.1: `__pycache__` untracked, requirements pinned; B24 found | `14e6d3f` |
| 2026-11-23 | P0.2: protocol log | see git log |
