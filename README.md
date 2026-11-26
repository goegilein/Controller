# Machine Control

Machine Control is the desktop app that runs the laser machine in the lab. It drives a Snapmaker Artisan (Marlin
firmware over USB) and the lab's own rotary stages (Waveshare ST3215 servos). It also shows the overview and laser
cameras and runs jobs that BildHatcher produces.

With 2.0 the machine logic moves into a core without Qt (`machine_core/`). The UI talks to that core only through
commands and events.
- What changed and why: [REVISION_PLAN.md](REVISION_PLAN.md)
- The rules behind it: [MachineControl_revision_notes.md](MachineControl_revision_notes.md)

## Start

```
pip install -r requirements.txt
python main_Controller.py                    # [--migrate-from <folder of a 1.x installation>\settings]
python -m pytest                             # all tests, no hardware needed (simulated Artisan and servos)
python build_executable.py                   # Windows exe (PyInstaller)
```

The port `simulator` connects to a simulated Artisan and simulated rotary stages, so you can try the app without a
machine.

## Where things are

| What | Where |
|---|---|
| Settings, stored positions, sample holders (yours) | `Documents\MachineControl\settings` (moved there from `settings\` once, P4.1) |
| Machine profile (work area, toolheads with laser offsets, limits, laser-off lines) | `Documents\MachineControl\profiles` – [docs/MACHINE_PROFILE.md](docs/MACHINE_PROFILE.md) |
| Run log, one JSON file per job | `Documents\MachineControl\runs` |
| Protocol log (every line to and from the machine) | `Documents\MachineControl\logs\protocol.log` |
| Job format | [docs/JCODE_SPEC.md](docs/JCODE_SPEC.md) |
| Hardware checks before a release | [tests/HARDWARE_CHECKLIST.md](tests/HARDWARE_CHECKLIST.md) |

## Safety in short

- The laser goes off on every stop, error, pause and job end, and when the app closes.
- **STOP (F9)** quick-stops the machine. **EMERGENCY STOP (F12)** sends `M112`. Both ask for confirmation, and Enter
  confirms. The machine's own E-stop button always works as well.
- Before anything moves, a job is checked against the work area, the power and feed limits, the toolhead, and the
  checksums in the J-code header.
- The rotary stages stop when the app ends, when a read or write fails, and when a wait times out. In the servo's
  position mode (C16) they hold their position even if the PC fails.

## Modules

### Machine core (`machine_core/`, no Qt)

| Module | Job |
|---|---|
| `worker.py` | `MachineWorker`: owns the serial port in its own thread. Takes commands, sends events, keeps the state machine. Switches the laser off on every failure. Holds `ArtisanConfig`. |
| `marlin.py` | Marlin connection: line protocol with ack, timeouts, quick stop (`M410`, `M112`). |
| `transport.py` | Serial port and the simulator transport. |
| `sim.py` | Simulated Artisan for tests and the `simulator` port. |
| `messages.py`, `state.py` | Commands, events and the machine states. |
| `job.py` | `JobRunner`: preflight checks, segments in absolute machine coordinates (`T_laser · T_step · J0`), pause and resume, rotary moves. |
| `jcode.py` | J-code and G-code reader: v0 and the v0.1 header. |
| `stages.py` | Rotary stages: the v1.0 PID in wheel mode, or the servo's own position mode. Also the simulator and the loop recorder. |
| `profile.py` | Machine profile: reading and checking. |
| `runlog.py` | Run log: one file per job. |

### Qt bridge and UI

| Module | Job |
|---|---|
| `main_Controller.py` | `build()` wires everything together; `main()` starts the app. |
| `machine_bridge.py` | `MachineBridge`: worker events into the UI thread. `ArtisanFacade` and `RotaryFacade` keep the old controller API for the UI modules. Also builds the settings and profile config. |
| `job_bridge.py` | `CoreProcessHandler`: the process steps of the UI run as core jobs. Bounding box, part rotation (P2.6). |
| `machine_safety_ui.py` | Machine bar: state, Stop and E-stop, error acknowledge, bright and dark mode. |
| `step_rotation_ui.py` | Dialog for a process step's part rotation, taken from a stored position. |
| `theme.py` | The Atelier look from BildHatcher (`GUI_files/styles`), dark or bright. |
| `Main_GUI_Interface.py` | Connections, ports, cameras, the settings dialog. |
| `Artisan_GUI_Interface.py` | Jogging, absolute moves, work position, enclosure outputs. |
| `Process_GUI_Interface.py` | Process steps, start, pause and cancel, bounding box. |
| `RotMotor_GUI_Interface.py` | Rotary stage panel. |
| `Maschine_Helper.py` | Stored positions, sample holders with the three-point fit. |
| `Camera_Controller.py`, `Camera_GUI_Interface.py`, `Interactive_Image_Control.py` | Cameras, calibration (homographies), click-to-move. |
| `Gcode_Plotter.py` | 3D preview of the G-code (OpenGL). |
| `Settings_Manager.py`, `Settings_Binder.py` | Settings layers and the generated settings dialog. |
| `PathManager.py` | Program and user folders, the user data migration. |
| `protocol_log.py` | Protocol log. |

### Kept as the v1.0 reference until the release clean-up

`Artisan_Controller.py`, `RotMotor_Cotroller.py`, `Process_Handler.py` (the job code) and their characterization
tests in `tests/test_characterization.py`. The app no longer uses them, except that `CoreProcessHandler` inherits the
step management of `ProcessHandler`. `ArduinoController.py` (the joystick) is switched off (C11).

### Tools

`tools/st3215_position_test.py` is the hardware test of the rotary servo's position mode. Its results are in
[tests/hardware/c16](tests/hardware/c16/README.md).
