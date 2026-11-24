# C16 – ST3215 position mode, hardware results

Motor 1 on the production rotary stage, `tools/st3215_position_test.py`, 2026-11-24.

| File | Run |
|---|---|
| `st3215_backup_1.json` | registers before the first run (wheel mode 1, limits 0..4095, phase 12, dead zones 1/1, offset 85) |
| `st3215_test_1_20261124_184015.csv` | run 1, `--turns 5` |
| `st3215_test_1_20261124_184353.csv` | run 1 again after a power cycle of the servo board, `--turns 3` |

## Result of run 1

- Multi-turn absolute mode works: goals up to +5 / −5 motor turns are reached, the present position is reported
  beyond 0..4095 and negative (full-angle feedback). Same values after the power cycle.
- **Accuracy:** the servo stops **2–4 ticks short** of the goal, from either side, for big and small moves. It
  **does not move at all** for a goal 1–3 ticks away. Its own loop shows the same break-away limit the user found in
  wheel mode, but it never oscillates.
- Stop (goal := present position) during a move: the servo brakes, overshoots about 150 ticks with acc 50 and comes
  back to the stop point. That is harmless, because the stage turns only while the head stands still and the laser is off.
- PC gone (port closed) in the middle of a move: the servo finishes the move and holds (7420 for goal 7422).
- Power cycle: the start position was the same (3328), but inside the first turn, so it does not show whether the
  multi-turn count survives. The PC does not depend on it: it reads the position on connect.

## Consequence

`ServoPositionMotor` corrects on the PC. Once the servo stands still, it aims past the target by the remaining error,
at most 3 times and 12 ticks. Run 2 (`--correction`) checks this on the machine before `control_mode = "position"` is used.
