# Release 2.0.0 – test run on the machine PC

This is the run sheet for the hardware test before release 2.0.0 (REVISION_PLAN.md P5.1). Work through it from top to
bottom and fill in the **Result** column: `OK`, or what you saw instead. Then commit and push the file together
with the files the steps ask for.

The steps follow [HARDWARE_CHECKLIST.md](HARDWARE_CHECKLIST.md). The numbers in brackets are its item numbers.

| | |
|---|---|
| Date | |
| Commit tested (`git log -1 --oneline`) | |
| Tester | |

**Safety:** until this run has passed, run jobs only on scrap material at low power, and keep the machine's own
emergency stop within reach. Do the USB cable test (step 3.12) at 0 % power only.

**For a finding:** open `Documents\MachineControl\logs\protocol.log`, copy the lines around the time of the
problem into a file `tests/hardware/release_2.0/<step>.log`, and note the step in the Result column.

---

## 1. Install and first start

| Step | What to do | Expected | Result |
|---|---|---|---|
| 1.1 | `git pull` on branch `revision_2.0`. Run from source (`python main_Controller.py`) or build the exe (`python build_executable.py` → `dist\`). | starts; the window title shows 2.0.0 | |
| 1.2 | First start. If 2.0 is **not** in the v1.0 folder, close it and start once with `--migrate-from "<v1.0 folder>\settings"`. (24) | a message lists the copied files: `Default_Settings.json`, `stored_positions.json`, `custom_sample_holders.json` | |
| 1.3 | Check the taken-over data. (24) | stored positions, sample holders, camera calibration and ports are as in v1.0 | |
| 1.4 | Start v1.0 once and close it again. (24) | v1.0 still starts with its own files | |
| 1.5 | Connect, then open `Documents\MachineControl\profiles\snapmaker_artisan.json`. (23) | no profile warning on connect; the laser offsets are the ones from the old settings | |

## 2. Recordings for the simulator (part A of the checklist)

For each line: start the app, do the steps, close the app. Then copy `Documents\MachineControl\logs\protocol.log`
to `tests/fixtures/recordings/<name>.log`. Delete or rename `protocol.log` before the next recording, so each file
holds only its own run.

| Name | What to do | Done |
|---|---|---|
| `connect_1064` | connect with the 1064 nm head, answer the homing question with Yes, wait 5 s, disconnect | |
| `connect_455` | the same with the 455 nm head | |
| `connect_no_home` | connect, answer No, disconnect | |
| `jog_and_wp` | jog X / Y / Z in step and continuous mode, set work position, move to work position, home | |
| `short_job` | a small J-code job from BildHatcher (2 clusters), run to the end | |
| `pause_resume` | the same job: pause after a few seconds, wait 10 s, resume, let it finish | |
| `cancel` | the same job, cancel in the middle | |
| `estop` | machine idle: press the machine's emergency stop button, then try to jog once | |
| `unknown_command` | optional: a job with a line `===` | |

## 3. Machine (part B of the checklist)

| Step | What to do | Expected | Result |
|---|---|---|---|
| 3.1 | Connect with both heads, one after the other. (1) | head detected, laser offset set, position shown | |
| 3.2 | Home all axes. (2) | position about X −30 / Y 403 / Z 405, the same after every homing | |
| 3.3 | Jog in step and continuous mode, all axes. (3) | moves; stops when released; the display follows | |
| 3.4 | Set the work position, move away, go back to the work position. (4) | returns to the same point | |
| 3.5 | Store a position, move away, go to it. (5) | returns to the same point | |
| 3.6 | Run the bounding box in camera mode and in laser mode. (6) | frames the job at the right place | |
| 3.7 | Short job, run to the end. (7) | burns correctly, ends at the start position, laser off | |
| 3.8 | Pause, wait 10 s, resume. (8) | no burn mark at the pause point; continues correctly | |
| 3.9 | Cancel during a job. (9) | stops, laser off; the head stays where it stopped | |
| 3.10 | Software E-stop (button or F12, confirm with Enter), then the machine's E-stop button. (10) | motion and laser stop at once; "E-STOP" shown; reconnect and home needed | |
| 3.11 | Stop (button or F9, confirm with Enter): while jogging, during a move and during a job. (14) | quick stop, laser off, state back to Idle | |
| 3.12 | **At 0 % power:** pull the USB cable during a job. Watch whether the laser keeps firing. (11, C13) | the job stops with a clear error. Write down what the laser did. | |
| 3.13 | **At 0 % power:** close the app during a job. (12) | laser off, rotary motors stop | |
| 3.14 | Work area: slowly move towards X 400, Y 0 and Z 0 and note how far each axis really goes. (15) | X max = ___ , Y min = ___ , Z min = ___ | |
| 3.15 | **The same job as with v1.0, on scrap**, at the same work position. Compare the two burns. (16) | identical burn position | |
| 3.16 | Holder fit with three points on a rotated holder → store the centre → process step "Rot" → apply → bounding box, then a short job on scrap. (19) | box and burn follow the holder's rotation; the tilt value is plausible | |

## 4. Rotary stages

| Step | What to do | Expected | Result |
|---|---|---|---|
| 4.1 | Wheel mode (the default): move to an angle, then a job with `R`. (13) | reaches the angle; the job waits for it | |
| 4.2 | Rotary moves with both cameras running. (17) | settles at the angle | |
| 4.3 | Stop the rotary while it turns (Stop, disconnect), and close the app while it turns. (18) | the stage stops at once | |
| 4.4 | Only if there is a second rotary motor: `python tools/st3215_position_test.py COMx --id 2`, then the same with `--correction`. (20, 20b) | all lines OK; the results land in `tests/hardware/c16` | |
| 4.5 | Settings dialog: set `rotary_motors.control_mode` to `position` (drop-down) and tick `record_loop`. Reconnect the rotary board. (21) | log line "rotary stages (position mode)" | |
| 4.6 | In position mode: repeat 4.1, 4.2 and 4.3, then one job with `R` on scrap. (21) | no oscillation, the angle on the tick, the stage stops at once | |
| 4.7 | Copy `Documents\MachineControl\logs\rotary_loop_*.csv` to `tests/hardware/c16/`. (21) | | |

## 5. Logs

| Step | What to do | Expected | Result |
|---|---|---|---|
| 5.1 | Start one job that will be refused (e.g. before homing). Open `Documents\MachineControl\runs`. (22) | one file per job (3.7, 3.9, 3.10 and the refused one), named by the start time; results `done` / `stopped` / `emergency stop` / `refused`; the right head and files | |
| 5.2 | Copy two or three of these files to `tests/hardware/release_2.0/runs/`. | | |

## 6. Documents

| Step | What to do | Done |
|---|---|---|
| 6.1 | Save the Snapmaker G-code reference (wiki page) as PDF or HTML to `docs/` – needed for C14 (does `G28` clear a `G92`?). | |

## 7. Decisions after the run

| Question | Answer |
|---|---|
| Make `position` the default for the rotary stages (after 4.6)? | |
| Open the PR `revision_2.0` → `main`? (merged only on your word) | |
