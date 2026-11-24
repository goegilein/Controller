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
| 0 – Safety net | in progress | P0.1, P0.2, P0.4, P0.5 done; P0.3 waits for recordings (checklist A) |
| 1 – Safety fixes in the existing code | merged into phase 2 | production stays on v1.0 until hardware tests; no fixes twice |
| 2 – Machine core without Qt (Marlin) | in progress | done (P2.1–P2.8); hardware checks pending |
| 3 – J-code and machine profile | in progress | P3.1 done; P3.2 header draft to decide |
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
| B01 | S | **Laser is never switched off on cancel, error or app exit.** The job only sends `M5` if the G-code footer is reached. Cancel, an exception in the job thread or closing the window (daemon thread killed) leave the laser mode / power active; in `M3` (constant) mode the laser may keep firing at standstill. | [Process_Handler.py:236-246](Process_Handler.py#L236-L246), no `closeEvent` | P1 | fixed in v2.0 (P2.3/P2.4), simulator-tested – hardware check pending |
| B02 | S | **A missing acknowledgement does not stop the job.** `_read_until` only logs on timeout; `send_command` swallows every exception. A lost USB connection makes the job "run" through all remaining lines, logging errors. | [Artisan_Controller.py:190-250](Artisan_Controller.py#L190-L250) | P2 | fixed in v2.0 (P2.2/P2.3), simulator-tested – hardware check pending |
| B03 | F | **Acknowledgements are off by one after every `M114`.** `M114` waits for `"X:"`, its `ok` stays in the buffer and is consumed by the next command (the "do it twice" workaround for `M1006` is caused by this). In practice the job runs with up to 2 lines in flight. Fixing it changes the streaming timing → see C3. | [Artisan_Controller.py:432](Artisan_Controller.py#L432), [:579](Artisan_Controller.py#L579) | P2 | fixed in v2.0 (P2.2), simulator-tested – hardware check pending |
| B04 | S | **Emergency stop is not reachable.** `emergency_stop()` is not wired to any button or hotkey (`stop_axis_button` in the .ui is unused). If it were: `M112` waits for the command lock (held up to 60 s by the job thread) and then 60 s for an `ok` that never comes. | [Artisan_Controller.py:510](Artisan_Controller.py#L510) | P1 | fixed in v2.0 (P2.3, P2.8c), simulator-tested – hardware check pending |
| B05 | S | **Jogging during pause, then resume, burns a line.** Move controls are enabled in `Paused`; after resume the next `G1` starts from the jogged position. | [Artisan_GUI_Interface.py:194-196](Artisan_GUI_Interface.py#L194-L196) | P1 | fixed in v2.0 (P2.4), simulator-tested – hardware check pending |
| B06 | S | **Rotary motors can keep spinning.** Wheel mode with a PC-side PID: if the control thread dies (the dummy `read_pos(0)` is outside the `try`), the app exits or `disconnect()` closes the port, the last speed stays active. `move_to_angle(wait_for_position=True)` waits forever (the 100 s timeout is unused) → job hangs. | [RotMotor_Cotroller.py:114-180](RotMotor_Cotroller.py#L114-L180) | P1 | fixed in v2.0 (P2.7, P2.8), simulator-tested – hardware check pending |
| B07 | S | **Widgets are changed from worker threads.** `Artisan_GUI_Interface.threadsafe_update_process_state` calls the update directly (the emitter is unused); `ProcessInterface.update_process_state` is registered as a plain callback and runs in the job thread. Can crash Qt during a job. | [Artisan_GUI_Interface.py:186-189](Artisan_GUI_Interface.py#L186-L189), [Process_GUI_Interface.py:44](Process_GUI_Interface.py#L44) | P1 | fixed in v2.0 (P2.8), simulator-tested – hardware check pending |
| B08 | S | **No checks before the job:** work area, power / speed limits, a known toolhead / laser offset. `get_toolhead_info` returns `"TEST"` if the machine does not answer, so a job can start with `laser_offset = None` (fails mid-way). Unknown toolhead is detected by the *number* of `M1006` lines (39 / 34). | [Artisan_Controller.py:568-612](Artisan_Controller.py#L568-L612), [Process_Handler.py:261](Process_Handler.py#L261) | P2 (`"TEST"` in P1) | fixed in v2.0 (P2.3, P2.5), simulator-tested – hardware check pending |
| B09 | F | A missing G-code file of a J-code is only printed and skipped; the `J1` indices then point to the wrong / no segment → `IndexError` mid-job, the rest of the step is skipped, **the next step still runs**. `J1` paths are resolved against the working directory, not the J-code folder. | [Process_Handler.py:578-579](Process_Handler.py#L578-L579) | P2 | fixed in v2.0 (P2.4), simulator-tested – hardware check pending |
| B10 | F | Bounding box in laser coordinates **adds the laser offset to the step's stored box every time** it is run. It also leaves a `G92` at the work position and runs in the UI thread. | [Process_Handler.py:409-442](Process_Handler.py#L409-L442) | P2 | fixed in v2.0 (P2.8b), simulator-tested – hardware check pending |
| B11 | S | `G91 … G90` sequences are not atomic: a continuous jog (own thread, `G91`) and an absolute move from the UI (`G90`) can interleave → a jog increment executed as an absolute target. | [Artisan_Controller.py:252-290](Artisan_Controller.py#L252-L290) | P2 | fixed in v2.0 (P2.3), simulator-tested – hardware check pending |
| B12 | F | Serial I/O in the UI thread: homing blocks the UI up to 60 s, every move / fit-point capture blocks; `disconnect()` sleeps 1.5 s. | many | P2 | fixed in v2.0 (P2.8), simulator-tested – hardware check pending |
| B13 | F | Position tracking dies on the first failed `M114` (`current_position = None` → `TypeError` in the setter) and is not restarted; every reconnect starts another tracking thread. | [Artisan_Controller.py:146-157](Artisan_Controller.py#L146-L157) | P2 | fixed in v2.0 (P2.3), simulator-tested – hardware check pending |
| B14 | F | `cancel_process` joins the job thread in the UI thread (UI frozen during the move back); called from the job thread itself on a failed sync it raises `cannot join current thread`. Cancel is refused when disconnected. | [Process_Handler.py:385-401](Process_Handler.py#L385-L401), [:358](Process_Handler.py#L358) | P2 | fixed in v2.0 (P2.8b), simulator-tested – hardware check pending |
| B15 | F | `origin_offset` / `is_homed` live only in the app: after a reconnect without homing (or an app crash) the machine still has the old `G92` shift, the app assumes none → all "absolute" positions (stored points, work positions) are wrong. Homing a single axis (`G28 Z`) resets the offset of *all* axes in the app (pinned in `manual_operations.txt`). | [Artisan_Controller.py:456-473](Artisan_Controller.py#L456-L473) | P2 | fixed in v2.0 (C5, P2.3), simulator-tested – hardware check pending |
| B16 | F | A settings change calls `get_toolhead_info` (`M1006` twice) – also during a running job. Typo `artisan.motoin.max_z_speed` (always the fallback 30). `move_axis_to` / `move_axis_absolute` clamp X/Y speed to the Z limit too. | [Artisan_Controller.py:96-108](Artisan_Controller.py#L96-L108), [:344](Artisan_Controller.py#L344) | P2 | fixed in v2.0 (P2.8a), simulator-tested – hardware check pending |
| B17 | F | Default work position `[1, 400, 400, 0]` when the position is unknown. `J0` without `Z` / `R` reuses stale values or raises `NameError`. | [Process_Handler.py:83](Process_Handler.py#L83), [:307-318](Process_Handler.py#L307-L318) | P2 | fixed in v2.0 (P2.4), simulator-tested – hardware check pending |
| B18 | F | After the job the work position is set to the *start* position, not restored to the user's previous one (intended? → C6). | [Process_Handler.py:237-238](Process_Handler.py#L237-L238) | P2 | fixed in v2.0 (P2.4), simulator-tested – hardware check pending |
| B19 | M | Icons loaded by relative path (`QIcon("GUI_files/resources/pause.png")`) – break in the built exe or another working directory. | [Process_GUI_Interface.py:294-304](Process_GUI_Interface.py#L294-L304) | P4 | open |
| B20 | M | 26 `__pycache__/*.pyc` files are tracked despite `.gitignore`. | repo | P0 | done |
| B21 | M | User data (settings, stored positions, homographies) is written next to the program, not into the user folder. | [PathManager.py](PathManager.py) | P4 | open |
| B22 | M | Rotary `connect()` reports "connected" even if `openPort()` fails; gear ratio 3 hard-coded (LaserMachine spec says 4:1 today). | [RotMotor_Cotroller.py:61-112](RotMotor_Cotroller.py#L61-L112), [:279](RotMotor_Cotroller.py#L279) | P2 | fixed in v2.0 (P2.7, P2.8a (3:1 per C8)), simulator-tested – hardware check pending |
| B24 | F | Comment stripping only cuts at `;`: BildHatcher's line `===;start of new Processblock===` is sent to the machine as `===` (Marlin answers "Unknown command" + `ok`). Parentheses comments are not handled. | [Process_Handler.py:555-563](Process_Handler.py#L555-L563) | P2 | fixed in v2.0 (P2.4), simulator-tested – hardware check pending |
| B25 | M | Coordinates are sent with float noise (`G0 X21.3 Y1.1999999999999993`, `X-21.299999999999997`) – harmless for Marlin, but noisy logs and longer lines. Seen in the golden files. | [Artisan_Controller.py](Artisan_Controller.py) moves | P2 | fixed in v2.0 (P2.3), simulator-tested – hardware check pending |
| B23 | M | Remaining-time estimate uses a fudge factor 2; long-move segmentation and the estimate ignore acceleration and `G2/G3`. | [Process_Handler.py:354](Process_Handler.py#L354) | P3 | open |
| B26 | F | Rotary tabs: `self.position_emitter` is overwritten per motor, so every motor's position is shown in the last tab and the earlier emitters are garbage collected. | [RotMotor_GUI_Interface.py:101-118](RotMotor_GUI_Interface.py#L101-L118) | P2 | fixed in v2.0 (P2.8c), simulator-tested – hardware check pending |

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
- [~] P0.3 **Simulated Artisan** ([tests/sim_artisan.py](tests/sim_artisan.py)): fake `serial.Serial` with
  G90/G91/G92/G28 position model, `M114`, `M1006`, `M118`, `M112`, unknown commands. Answers are modelled after
  Marlin – **to be checked against the recordings** of [tests/HARDWARE_CHECKLIST.md](tests/HARDWARE_CHECKLIST.md)
  section A (`M114` format, `M1006` text per head, `M118` prefix, G28 vs G92 shift, `busy:`).
- [x] P0.4 **Characterization tests** ([tests/test_characterization.py](tests/test_characterization.py), golden
  files in `tests/golden/`): connect (both heads), manual operations, a BildHatcher cluster file as `.nc` job,
  a J-code job with two clusters + rotary axis + a second step, bounding box twice in laser coordinates, and
  `NCCodeInterpreter` output (segments, times, box). `python -m pytest`, no hardware, < 1 s.
  Not covered (timing dependent): pause / resume, cancel, continuous jog, the position-tracking thread – they
  get tests on the new core (P2.3 / P2.4). Regenerate only for agreed changes: `UPDATE_GOLDEN=1 python -m pytest`.
- [x] P0.5 Manual hardware checklist and list of recordings for the simulator:
  [tests/HARDWARE_CHECKLIST.md](tests/HARDWARE_CHECKLIST.md).

### Phase 1 – Safety fixes in the existing code

Merged into phase 2 (decision 2026-11-23): production keeps running v1.0 until the hardware tests, so the fixes
are made once, in the new core, and tested on the simulated machine. Each P1 item stays as an acceptance test.


- [-] P1.1 (→ phase 2) B01 laser off (`M5`, `M9`) on cancel, on exception in the job thread and in a `closeEvent` / `aboutToQuit`.
- [-] P1.2 (→ phase 2) B04 emergency-stop button + hotkey; `M112` written directly to the port, bypassing the lock, no ack wait.
- [-] P1.3 (→ phase 2) B05 move controls stay disabled in `Paused` (or see C4).
- [-] P1.4 (→ phase 2) B06 rotary motors: speed 0 on disconnect / exit / control-loop exception, timeout in `move_to_angle`.
- [-] P1.5 (→ phase 2) B07 process-state updates to widgets through signals.
- [-] P1.6 (→ phase 2) B08 part: refuse to start a job without a detected toolhead (remove the `"TEST"` return).

### Phase 2 – Machine core without Qt (Marlin)

- [x] P2.1 [machine_core/messages.py](machine_core/messages.py) (commands / events, JSON round trip), [machine_core/state.py](machine_core/state.py) (states and allowed transitions: no way from error / estop back into a job, error needs an acknowledge, estop needs a reconnect); tests in `tests/test_core_messages_state.py`.
- [x] P2.2 [machine_core/transport.py](machine_core/transport.py) (serial + simulator), [machine_core/marlin.py](machine_core/marlin.py):
  reader thread, strict ack matching (B03), `Error:` / timeout / lost connection raise instead of being swallowed (B02),
  `busy:` extends the deadline, `write_now` for stop / E-stop without the send lock (B04). The simulator moved to
  [machine_core/sim.py](machine_core/sim.py) and got a realtime planner (16 blocks, ack when queued), a laser model and
  fault injection. Tests `tests/test_core_marlin.py` (both sim modes): one `M1006` is enough now; with one line in
  flight 200 short hatch segments at 10× speed never let the planner run empty (C3, in-process – real USB latency to
  be checked on the machine); M3 standstill emission is visible in the simulator (C13).
- [x] P2.3 [machine_core/worker.py](machine_core/worker.py): the only thread on the port; `submit()` never blocks;
  machine coordinates without `G92` (C5), app-side work position; absolute moves only after homing; atomic
  `G91 … G90` (B11); M114 polling while idle (B13); one `M1006`, unknown head → error (B08); Stop = `M410` + laser
  off, E-stop = `M112` → `estop` until reconnect (B04, confirmation in the UI per C2); laser off on error, ack timeout,
  lost connection, exception in the thread and shutdown (B01); coordinates without float noise (B25); simulator
  port `"simulator"` for dry runs. Tests `tests/test_core_worker.py` (15 scenarios).
  Found on the simulator: a stop racing with a line that is just being sent let that line reach the machine after
  `M410` – fixed by `MarlinConnection.stop()` blocking all sends under the write lock until the worker finished the
  stop. Note: Marlin acks a move when it is queued, so `idle` does not mean the head stands still (as in v1.0).
- [x] P2.4 [machine_core/jcode.py](machine_core/jcode.py) (J-code v0 reader, `J1` relative to the J-code folder,
  missing files / `G2 G3 G28 G92 G53–G59` refused at load, non-command lines skipped with a warning, v1.0
  segmentation ≤ 1 s) and [machine_core/job.py](machine_core/job.py) (runner on the worker thread):
  `machine = T_laser · T_step · Trans(J0) · p_raw` with a 4×4 `T_step` per step (rotation supported), absolute G90
  lines in machine coordinates, `M400` before every segment move and before the rotary axis turns, pause per C4
  (drain, `M5`, restore mode line and power words on resume), no jogging in pause, laser off and back to the start
  at the end, work position untouched. Tests `tests/test_core_job.py` (12), among them: **the burn path of a
  J-code job with two steps, rotary axis and segmentation is identical to v1.0** (machine positions of every `G1`,
  laser state), a 90° rotated part, pause / stop / E-stop / cable pulled during a job.
  **Intended changes vs v1.0** (to confirm on the machine): sync is `M400` only (no `M118`); the head moves
  directly to each segment origin (v1.0: to the camera position, then by the laser offset); after a *Stop* the
  head stays where it stopped (v1.0 cancel drove back to the start – moving without the user is avoided); `J0`
  without an axis means 0 (v1.0 reused the previous value); `M5`, `M9` are always sent at the end of a job.
- [x] P2.5 Preflight checks: work area, toolhead / laser offset known, files present, rotary motor assigned,
  power / speed within the profile (B08, B17). `JobRunner.prepare` refuses a job before anything moves if a move or a
  segment origin, in laser machine coordinates (rotation included), leaves `ArtisanConfig.work_area`; if `S` is
  outside 0..255 or `P` outside 0..100 (`M3` / `M4` / `G1`); if `F` ≤ 0 or above `max_feed` (not set: Artisan limit
  unknown). Absolute manual moves (`MoveTo`) outside the work area are refused too. Work area = datasheet,
  400 × 400 × 400 mm from the homing point (0, 0, 0) – **VERIFY** on the machine (homing position, real travel,
  whether the work area differs per toolhead). Relative jogs are not checked (the firmware's soft endstops apply).
- [x] P2.6 Coordinates (C5): no `G92`; per-step 4×4 transform raw → machine applied to every `G0/G1` (X, Y, Z; F unchanged
  for rigid transforms); camera → laser offset as a translation; stored positions / fit points stay valid (already
  absolute). Fixes B10, B15, B18, B25.
  Part rotation per step (decisions 2026-11-24): the three-point holder fit (`CustomSampleHolders`) already computed
  a full rotation but only stored the centre – a stored position now keeps an optional `rotation` (3×3, saved in
  `stored_positions.json`; old files stay valid). A process step takes position + rotation from a stored position;
  the job uses **only the rotation about Z** (`rz_only`), the tilt is shown with a warning above 0.5° and not
  applied (paths stay flat). Step widget: button "Rot x.xx°" → dialog with the matrix, Rz, tilt, "apply stored
  position", "reset". Rel X/Y/Z of a step are shown in the part frame (= G-code coordinates); bounding box rotates
  with the part. Without a rotation everything is as before. Rotary gear ratio per motor from the settings (C16).
- [x] P2.7 `stages.py` from `RotMotor_Cotroller` with safe stop and timeouts; direction per C8.
  `machine_core/stages.py`: `RotaryStages` (no Qt) with the v1.0 PID unchanged, bus interface (`ScservoBus` real,
  `SimStageBus` simulated with acceleration and faults). Speed 0 to every motor on disconnect, interpreter exit
  (atexit), any exception in the control loop and 5 failed reads / writes in a row (fault, waits raise until
  reconnect). `move_to_angle(wait)` has a timeout (default 100 s, as the unused v1.0 value) and a cancel hook; the
  job runner passes the machine stop, so Stop / E-stop end a rotary wait at once and stop the stage. A stage error
  in a job → machine error with the laser off. Two v1.0 bugs fixed on the way: `stop_motor` only wrote speed 0 and
  the loop drove on to the old target 20 ms later; a wait could return before the move started (relied on a 0.1 s
  sleep). Not covered: a killed process / PC power loss leaves the last speed active (wheel mode has no watchdog –
  VERIFY in the STS3215 manual). The old `RotMotor_Cotroller` is replaced in P2.8. Fixes B06.
- [x] P2.8 QtBridge; switch `Artisan_GUI_Interface`, `Process_GUI_Interface`, `Maschine_Helper`,
  `Interactive_Image_Control` to commands / events. Characterization tests updated **only** for agreed changes.
  Done in three commits:
  - [x] P2.8a `machine_bridge.py`: `MachineBridge` (worker events → queued Qt signal, UI thread only, B07),
    `ArtisanFacade` (the old `ArtisanController` methods the UI calls, as commands; positions from the cache, no I/O
    in the UI thread, B12), `RotaryFacade` (old `RotMotorCotroller` API on `machine_core.stages`; a click never
    raises). Mapping of the old API: `move_axis_to("absolute")` = work frame, one `G0` (as v1.0);
    `move_axis_absolute` = machine coordinates, Z-safe; `home_axis(False)` from `clicked()` homes all (v1.0 sent
    `G28 False`); the homing question after connect stays (needed for machine coordinates). Settings: the misspelt
    `max_z_speed` key is fixed (B16; value is 30 in the default settings, so no change); the worker's config is only
    replaced while disconnected (B16: no `M1006` during a job).
  - [x] P2.8b `job_bridge.CoreProcessHandler` (subclass of the v1.0 `ProcessHandler`, which stays untouched as the
    reference): step management inherited unchanged; start → `StartJob` with `step_transform(x, y, z)` and the rotary
    base angle r per step; pause / resume → `Pause` / `Resume`; cancel → `Stop` (no return move, agreed in P2.4);
    process state and remaining time from the machine's events (UI thread, B07; no `join` in the UI, B14). Bounding
    box: `MoveTo` in machine coordinates, the stored box is not changed and no `G92` is left (B10). Tested: a job
    from the UI's process steps burns exactly what the runner burns (which equals v1.0, P2.4).
  - [x] P2.8c `main_Controller` uses the bridge, the facades and `CoreProcessHandler`. `machine_safety_ui.MachineBar`
    (tool bar, the .ui file is unchanged): machine state, **Stop (F9)** and **E-stop (F12)**, both with a
    confirmation where Enter confirms (C2), hotkeys application-wide; "Acknowledge error" button; errors in the
    status bar. Port list has `simulator` for the Artisan and the rotary stages (virtual machine for dry runs). On
    exit: laser off (worker shutdown) and stages stopped. TCP is gone from the used path (the settings keys stay
    until the settings clean-up in phase 4). Fixed on the way: B26 (rotary tabs); a broken position display can
    no longer stop the rotary control loop. Simulator: stages share a virtual clock with the PID (`cycle_dt`) so
    tests do not depend on PC load – what load does on the real PC is C16. Tested: `tests/test_app_smoke.py` builds
    the real UI modules on the virtual machine and clicks through jog, move, work position, homing, a process,
    Stop with confirmation, E-stop. The app starts with a real window without errors.
    The old `Artisan_Controller` / `RotMotor_Cotroller` / `ProcessHandler` job code and their characterization tests
    stay until the release clean-up (phase 4) as the v1.0 reference.

### Phase 3 – J-code and machine profile (prepare v3.0)

- [x] P3.1 Write down today's J-code as spec v0 (`J0 X Y Z R`, `J1 <file>`, comments) – the reader stays compatible.
  [docs/JCODE_SPEC.md](docs/JCODE_SPEC.md) section 1, tests in `tests/test_jcode.py`. Reader fixes found while
  writing it: parentheses in J-code lines are no comments again (as v1.0 – the P2.4 reader stripped them, so
  `J1 job (1).nc` would not be found); a bad `J0` number or word is a clear refusal instead of an internal error;
  `G20` (inch) is refused. Section 2 = header draft for P3.2.
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
| C1 | Firmware version, connection, own modules | **answered:** USB only, TCP not used → remove. Own hardware: rotary stages and cameras only. Firmware version still to read out. |
| C2 | Emergency stop | **decided:** the Artisan has a hardware emergency stop. Software has two levels – *Stop* (`M410` quick stop + `M5`, keeps the connection) and *E-Stop* (`M112`) – **both ask for confirmation** first (Enter confirms, so it stays fast). Hotkey opens the same confirmation. |
| C3 | Streaming window | **decided:** strict ack matching (fixes B03), one line in flight. Marlin acknowledges when a line is queued, so the planner stays full while we stream; it only drains at the sync point (`M400`). Today's accidental 2-line window is dropped – measure throughput in the simulator, check with a test burn later. |
| C4 | Pause | **decided:** laser off (`M5`) in pause, restore laser mode / power on resume; no jogging in pause. Plus C13. |
| C5 | Work position / coordinates | **decided:** the app works in **absolute machine coordinates** and never sends `G92`. Every G-code coordinate is transformed in the app before sending; each process step holds a full 4×4 transform (rotation + translation) from the job's raw data into machine coordinates, so a rotated part can be processed (fits the sample-holder measurement and stored positions, which are already absolute). Homing is required after every connect. The "work position" stays as an app-side reference only. See C14. |
| C15 | Does the Snapmaker firmware have Marlin's emergency parser (`M112` / `M410` act on arrival)? Without it, a software stop only acts after the queued moves (≤ 16 blocks) or a running `M400`. | **Yes** (user, 2026-11-23). The simulator default `emergency_parser=True` matches; still worth one look in the protocol recording of a stop (checklist A). |
| C16 | Rotary PID under CPU load | open. User: only oscillation in the **tenth-of-a-degree** range seen, never degrees; stable with today's parameters. Drive: Waveshare **ST3215**, bought GT2 belt gear **20:60 (3:1)**, a **5:1** upgrade is planned (ratio now per motor in the settings: `rotary_motors.gear_ratio`, `gear_ratios`). **Full 360° on the part is required** (multi-turn at the motor). Options: A) PID hysteresis / I-freeze / D filter, B) servo position mode (multi-turn – VERIFY in the Waveshare ST3215 wiki), C) own process for the loop. Next: loop recording on the machine, simulator with belt backlash; decide with the user (affects production). **2026-11-24:** user observes the oscillation only in the *computed* motor positions, about 3 motor steps; single-step positioning in wheel mode does not work (tested) → the I-term builds up, the motor jumps too far, back again (stick-slip hunting). Not reproduced on the simulator with simple stiction / break-away / latency models – needs a recording of the loop. Register map (STS protocol, `sms_sts.py`): mode 33, CW / CCW dead zone 26 / 27; Waveshare: motor (step) mode positions relative within ±7 turns, servo mode 360° absolute at 360°/4096. |
| C14 | Does `G28` clear a `G92` shift left by v1.0 or another program, and does `M114` then report machine coordinates? Are `G53` / `G92.1` supported? | to verify with the G-code reference (the wiki blocks automated fetches – user saves a copy) and on the machine; until then: home on connect and refuse jobs before homing |
| C6 | Work position after a job | **decided:** known bug – restore the previous work position (B18). |
| C7 | Toolhead detection | postponed (needs recordings). |
| C8 | Rotary stages | **decided:** own hardware, driven by this software (not by the Snapmaker controller); PC-side PID stays, with safety fixes (B06). Gear ratio **3:1 is correct** (LaserMachine Nur_Gantry.md Kap. 8.1 says 4:1 – to be corrected there). |
| C9 | User data folder | **decided:** move to `Documents\MachineControl` with a one-time migration. |
| C10 | Owner of machine profiles | **decided:** one profile file per machine with a `gcode` section (BildHatcher) and a `machine` section (controller: work area, limits, toolheads with laser offset, rotary axes, laser-off sequence), in a shared folder (`Documents\MachineControl\profiles`); into the shared package in v3.0. The Artisan has **two exchangeable heads** (1064 nm / 455 nm) – the head is a property of the job / profile entry, the controller checks it against the detected head. |
| C11 | Arduino joystick, autofocus | **decided:** Arduino stays unchanged (maybe re-enabled later); autofocus is work in progress and must be integrable later – keep camera code movable to the core. |
| C12 | Priorities | **answered:** production works with v1.0, no time pressure; hardware tests later → work as far as possible on the simulated machine. |
| C13 | Laser keeps firing when commands stop (PC crash, cable lost) | open. The PC cannot act after a lost connection – needs a firmware or hardware answer. Known: the Artisan firmware switches the laser off on `G0` in M3 and M4 (Snapmaker forum changelog). Unknown: standstill in M3 with no further commands. To do: hardware test at low power (stop the stream in the middle of a `G1`), look for a laser idle timeout in the firmware; if none, prefer `M4` (dynamic) in BildHatcher's profile and / or a hardware watchdog. |

---

## 7. Decisions

| Date | Decision |
|---|---|
| 2026-11-24 | Phase 3 scope: (3) the controller **checks** that a job fits the machine / head (J-code header, old J-codes without header still accepted); (4) laser-off at the end may be sent twice (job footer + controller) – no conflict; (5) **no BildHatcher changes before v3.0** – phase 3 defines the format, the controller reads it optionally; (6) run log as files in a default output folder, one per job, named by the start time stamp. P2.6 before phase 3. Hotkeys F9 / F12 confirmed. |
| 2026-11-23 | Branch `revision_2.0` created from `main` (`3605785`, contains `stored_pos`). |
| 2026-11-23 | Answers to C1–C12 (section 6). Phase 1 merged into phase 2; work on the simulated machine until hardware tests are possible. TCP is removed. |
| 2026-11-23 | C15: the Snapmaker firmware has the emergency parser. P2.5: check against the datasheet work area for now (VERIFY). |

---

## 8. Work log

| Date | What | Commit |
|---|---|---|
| 2026-11-23 | Inventory, bug list, phase plan (draft) | `fbb214b` |
| 2026-11-23 | P0.1: `__pycache__` untracked, requirements pinned; B24 found | `14e6d3f` |
| 2026-11-23 | P0.2: protocol log | `f99f194` |
| 2026-11-23 | P0.3 (draft) / P0.4 / P0.5: simulated Artisan, 8 characterization tests, hardware checklist; B25 found, B15 extended | `380e6d5` |
| 2026-11-23 | Decisions C1–C12 | `ab0270d` |
| 2026-11-23 | P2.1: messages and state machine | `3373954` |
| 2026-11-23 | Decision C5: absolute machine coordinates, per-step transform; C14 | `711e919` |
| 2026-11-23 | P2.2: Marlin protocol, transports, realtime simulator | `7a1bb39` |
| 2026-11-23 | P2.3: machine worker, stop race found and fixed on the simulator | `4778766` |
| 2026-11-23 | P2.4: J-code reader and job runner in machine coordinates; burn path equal to v1.0; C15 | `62a9519` |
| 2026-11-23 | P2.5: preflight – work area, power, feed; manual moves inside the work area; C15 answered | `f1d4637` |
| 2026-11-23 | P2.7: rotary stages without Qt – safe stop, timeouts, cancel by the machine stop (B06) | `037824b` |
| 2026-11-23 | P2.8a: Qt bridge, Artisan and rotary facades with the old API | `468fe90` |
| 2026-11-23 | P2.8b: process steps run as core jobs; bounding box without G92 (B10) | `45f9124` |
| 2026-11-23 | P2.8c: app on the machine core, Stop / E-stop bar with confirmation and F9 / F12, simulator port; B26, C16 | `8a568ef` |
| 2026-11-24 | Decisions C10, phase 3 scope; rotary gear ratio per motor | `363e595` |
| 2026-11-24 | P2.6: part rotation per step from stored positions (Rz only, tilt shown) | `eb7e6e8` |
| 2026-11-24 | P3.1: J-code spec v0, reader fixes (parentheses in file names, bad J0, G20); C16 analysis | see git log |
