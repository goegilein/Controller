# Hardware checklist – Snapmaker Artisan (REVISION_PLAN.md P0.5)

Run before every merge to `main` and after every change to what is sent to the machine. Write the result
(date, commit, toolhead, OK / finding) into the work log of REVISION_PLAN.md.

Every session writes `%USERPROFILE%\Documents\MachineControl\logs\protocol.log`. Attach the relevant part of the
log to a finding.

**Safety while testing:** v2.0 switches the laser off on every stop, error and exit and blocks jogging in a pause,
but this has only been tested on the simulated machine. Until this checklist has passed: run jobs only on scrap
material at low power, and keep the machine's own emergency stop within reach.

**Release 2.0.0:** part A, then part B in order. Items marked "done" were run already (date in the item).

## A. Recordings for the simulator (once, then after firmware updates)

Start the app, do the step, close the app, copy `protocol.log` to `tests/fixtures/recordings/<name>.log`.

| Name | What to do |
|---|---|
| `connect_1064` | connect with the 2 W 1064 nm head, answer the homing question with Yes, wait 5 s, disconnect |
| `connect_455` | the same with the 40 W 455 nm head |
| `connect_no_home` | connect, answer No, disconnect |
| `jog_and_wp` | jog X/Y/Z in step and continuous mode, set work position, move to work position, home |
| `short_job` | a small J-code job (2 clusters) from BildHatcher, to the end |
| `pause_resume` | the same job, pause after a few seconds, wait 10 s, resume (do not jog), let it finish |
| `cancel` | the same job, cancel in the middle |
| `estop` | machine idle: press the machine's emergency stop button, then try to jog once |
| `unknown_command` | (optional) send a job with a line `===` – shows the firmware's answer to unknown commands |

## B. Checklist

| # | Step | Expected |
|---|---|---|
| 1 | Connect (both heads, one after the other) | toolhead detected, laser offset set, position shown |
| 2 | Home all axes | homes; position about X −30 / Y 403 / Z 405 (measured 2026-11-26), the same after every homing |
| 3 | Jog step and continuous, all axes | moves, stops on release, display follows |
| 4 | Set work position, move away, move to work position | returns to the same point |
| 5 | Stored position: store, move away, go to it | returns to the same point |
| 6 | Bounding box (camera and laser mode) | frames the job at the right place |
| 7 | Short job to the end | burns correctly, ends at the start position, laser off |
| 8 | Pause, wait 10 s, resume | no burn mark at the pause point, continues correctly |
| 9 | Cancel during a job | stops, laser off; v2.0: the head **stays** where it stopped (no return move) |
| 10 | Emergency stop: software (button / F12, confirm with Enter) and machine button | motion and laser stop at once; v2.0 shows "E-STOP", reconnect + home needed |
| 11 | USB cable pulled during a job (at 0 % power) | job stops with a clear error; the laser is not firing (see C13) |
| 12 | Close the app during a job (at 0 % power) | laser off, rotary motors stop |
| 13 | Rotary stage: move to angle, job with `R` | reaches the angle, job waits for it |
| 14 | v2.0: Stop (button / F9, confirm with Enter) while jogging, moving and in a job | quick stop (`M410`), laser off, state back to Idle |
| 15 | v2.0: work area – **home measured 2026-11-26: X ≈ −30, Y ≈ 403, Z ≈ 405** (top left, Y fully forward; limits 1 mm inside). Still open: X max, Y min, Z min (slowly towards 400 / 0 / 0) | values for the profile's `work_area` |
| 16 | v2.0: job positions – the same job as in v1.0 on scrap | identical burn position (C5 machine coordinates) |
| 17 | v2.0: rotary moves with both cameras running (C16) | settles at the angle, no oscillation |
| 18 | v2.0: stop the rotary while it turns (disconnect / Stop) and close the app while it turns | stage stops at once |
| 19 | v2.0: holder fit with three points on a rotated holder → store centre → step "Rot" → apply → bounding box, then a short job on scrap | box and burn follow the holder's rotation; tilt value plausible |
| 20 | **done 2026-11-24 (motor 1)** – repeat for every other rotary motor. C16: `python tools/st3215_position_test.py COMx --id 1` for each rotary motor (stage free, no part); then once the manual power-cycle step it prints | all lines OK: on the tick (±1), beyond one turn, stop, holds without the PC; send the CSV + output back |
| 20b | **done 2026-11-26 (motor 1, run 3: 18/18)** – repeat for every other rotary motor. C16: `python tools/st3215_position_test.py COMx --id <n> --correction` (tests/hardware/c16) | every line OK (±1 tick after at most 3 corrections); results land in tests/hardware/c16 – push them |
| 21 | C16, after 20b is OK: settings `rotary_motors.control_mode = "position"`, `record_loop = true`; items 13, 17, 18 again; one job with `R` on scrap | no oscillation, angle on the tick; `Documents\MachineControl\logs\rotary_loop_*.csv` back |
| 22 | v2.0 (P3.4): after items 7, 9, 10 and one refused job, open `Documents\MachineControl\runs` | one file per job, named by the start time; result done / stopped / emergency stop / refused; the right head and files |
| 23 | v2.0 (P3.3): first start on the production PC, then open `Documents\MachineControl\profiles\snapmaker_artisan.json` | laser offsets = the ones in the old settings; connect shows no profile warning; item 16 still burns at the same place |
| 24 | v2.0 (P4.1): first start of 2.0 on the production PC. If 2.0 is not in the v1.0 folder: start once with `--migrate-from <v1.0 folder>\settings` | the message lists the copied files; stored positions, sample holders, camera homographies and ports as in v1.0; v1.0 still starts with its own files |
