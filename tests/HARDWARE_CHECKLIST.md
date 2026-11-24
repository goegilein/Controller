# Hardware checklist – Snapmaker Artisan (REVISION_PLAN.md P0.5)

Run before every merge to `main` and after every change to what is sent to the machine. Write the result
(date, commit, toolhead, OK / finding) into the work log of REVISION_PLAN.md.

Every session writes `%USERPROFILE%\Documents\MachineControl\logs\protocol.log`. Attach the relevant part of the
log to a finding.

**Safety while testing the baseline:** today's code does not switch the laser off on cancel, error or exit (B01),
and jogging during pause burns a line on resume (B05). Until Phase 1 is done: run jobs only on scrap material at
low power, keep the machine's own emergency stop within reach, and never jog during a pause.

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
| 2 | Home all axes | homes, position 0 / 0 / 0 |
| 3 | Jog step and continuous, all axes | moves, stops on release, display follows |
| 4 | Set work position, move away, move to work position | returns to the same point |
| 5 | Stored position: store, move away, go to it | returns to the same point |
| 6 | Bounding box (camera and laser mode) | frames the job at the right place |
| 7 | Short job to the end | burns correctly, ends at the start position, laser off |
| 8 | Pause, wait 10 s, resume | no burn mark at the pause point, continues correctly |
| 9 | Cancel during a job | stops, laser off; v2.0: the head **stays** where it stopped (no return move) |
| 10 | Emergency stop: software (button / F12, confirm with Enter) and machine button | motion and laser stop at once; v2.0 shows "E-STOP", reconnect + home needed |
| 11 | USB cable pulled during a job (only at 0 % power until Phase 1) | job stops with a clear error, laser off |
| 12 | Close the app during a job (only at 0 % power until Phase 1) | laser off, rotary motors stop |
| 13 | Rotary stage: move to angle, job with `R` | reaches the angle, job waits for it |
| 14 | v2.0: Stop (button / F9, confirm with Enter) while jogging, moving and in a job | quick stop (`M410`), laser off, state back to Idle |
| 15 | v2.0: work area – after homing, move to 400 / 400 / 400 (slowly) and note the real limits; homing point = 0 / 0 / 0? | values for `ArtisanConfig.work_area` (P2.5, VERIFY) |
| 16 | v2.0: job positions – the same job as in v1.0 on scrap | identical burn position (C5 machine coordinates) |
| 17 | v2.0: rotary moves with both cameras running (C16) | settles at the angle, no oscillation |
| 18 | v2.0: stop the rotary while it turns (disconnect / Stop) and close the app while it turns | stage stops at once |
| 19 | v2.0: holder fit with three points on a rotated holder → store centre → step "Rot" → apply → bounding box, then a short job on scrap | box and burn follow the holder's rotation; tilt value plausible |
| 20 | C16: `python tools/st3215_position_test.py COMx --id 1` for each rotary motor (stage free, no part); then once the manual power-cycle step it prints | all lines OK: on the tick (±1), beyond one turn, stop, holds without the PC; send the CSV + output back |
| 21 | C16, after 20 is OK: settings `rotary_motors.control_mode = "position"`, `record_loop = true`; items 13, 17, 18 again; one job with `R` on scrap | no oscillation, angle on the tick; `Documents\MachineControl\logs\rotary_loop_*.csv` back |
