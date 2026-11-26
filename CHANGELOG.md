# Changelog

## 2.0.0 – release candidate (2026-11-26)

This is a full revision of Machine Control. Branch `revision_2.0`, details in [REVISION_PLAN.md](REVISION_PLAN.md).
Every change was tested on the simulated machine. The checks on the real machine are in
[tests/HARDWARE_CHECKLIST.md](tests/HARDWARE_CHECKLIST.md) and must be done before the release.

### Safety

- **The laser goes off on every stop, error, pause, job end and app exit.** In 1.x it went off only when the G-code
  footer was reached (B01).
- A lost connection or a missing acknowledgement **ends the job with an error**. In 1.x the job "ran" on without the
  machine (B02, B03).
- **STOP (F9)** and **EMERGENCY STOP (F12)** in a new machine bar, each with a confirmation (Enter confirms). In 1.x
  the emergency stop was not reachable (B04).
- **Checks before a job starts:** a job is refused before anything moves if it leaves the work area, has power or
  feed outside the limits, comes before homing or finds an unknown toolhead (B08, B09).
- No jogging while a job is paused. Resume restores laser mode and power (B05).
- **Rotary stages never keep spinning.** They stop on disconnect, on app exit, on bus errors, when a wait times out
  and on Stop (B06).
- Widgets are only changed in the UI thread, and serial I/O no longer runs in the UI thread (B07, B12).

### Machine and jobs

- New machine core without Qt (`machine_core/`): one thread owns the port and works through commands, events and an
  explicit state machine.
- **Jobs run in absolute machine coordinates** without `G92`. Burn positions are unchanged (C5).
- **The work position is no longer overwritten after a job** (B18), and a cancel leaves the head where it stopped.
- **Part rotation per process step:** the rotation is taken from a stored position, such as the three-point holder
  fit. Rotation about Z is applied, tilt is only shown (P2.6).
- The bounding box no longer shifts the stored box and leaves no `G92` behind (B10).
- **J-code v0.1 header (optional):** format version, machine, toolhead and a SHA-256 per file. A mismatch is refused,
  and paths are relative. Old J-codes without a header run as before. See [docs/JCODE_SPEC.md](docs/JCODE_SPEC.md).
- File names with parentheses work. `G20`, arcs, `G28` and `G92` inside jobs are refused. BildHatcher's
  `===` lines are no longer sent to the machine (B24).
- **Machine profile** `Documents\MachineControl\profiles\snapmaker_artisan.json`: work area (from the measured home
  position), limits, both heads with laser offsets, laser-off lines. Your laser offsets are taken over once. See
  [docs/MACHINE_PROFILE.md](docs/MACHINE_PROFILE.md).
- **Run log:** one file per job in `Documents\MachineControl\runs`, with result, head, files and checksums.
- **Protocol log** of every line to and from the machine: `Documents\MachineControl\logs\protocol.log`.

### Rotary stages

- **New servo position mode** (`rotary_motors.control_mode = "position"`): the ST3215 positions itself and the PC
  corrects the last ticks. Measured to ±1 tick (±0.03° at 3:1), with no oscillation. The servo also holds its
  position if the PC fails. Default is still `"wheel"` (the 1.x controller) until checklist item 21 is done (C16).
- Gear ratio per motor in the settings (`gear_ratio`, `gear_ratios`), ready for the 5:1 upgrade.
- Optional loop recording `rotary_motors.record_loop`.
- Each rotary tab shows its own motor's position (B26).

### User interface

- **Atelier look from BildHatcher**, dark or bright: use the "Bright mode" button or the `ui.theme` setting.
- Settings with fixed values are drop-downs in the settings dialog.
- `simulator` port for trying the app without a machine.

### User data

- Settings, stored positions and sample holders now live in **`Documents\MachineControl\settings`**. They are copied
  once from the old place on the first start (B21).
- The 1.x files are not changed, so 1.x keeps working with them.
- If 2.0 is installed somewhere else than 1.x, start it once with
  `--migrate-from "<1.x folder>\settings"`.

### Known open points

- Laser behaviour when the connection is lost in the middle of a burn (C13).
- Whether `G28` clears a `G92` left by 1.x (C14).
- Toolhead detection relies on the length of the `M1006` answer (C7).
- After an E-stop the job thread may wait up to 10 s for an acknowledgement before it ends. Laser, state and run log
  are correct in the meantime.
- The "Crosshair is OFF" button text is slightly clipped.
