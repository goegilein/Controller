# Machine profile

One JSON file per machine (decision C10). It holds everything that is specific to that machine: the G-code that
BildHatcher writes for it, and what the machine control needs to run it safely. This document describes format 1
(REVISION_PLAN.md P3.3). The reader is `machine_core/profile.py`, and the tests are in `tests/test_profile.py`.

## Where the files are

- Bundled with the controller: `profiles/<id>.json`. Today that is `snapmaker_artisan.json`.
- In use: `Documents\MachineControl\profiles\<name>.json`. The first time a profile is used, the bundled file is
  copied there, and the user edits that copy. The setting `artisan.machine_profile` chooses the file. The default is
  `snapmaker_artisan`.
- When the copy is made the first time, the old settings are moved into it, so a calibrated laser offset is kept.
  These settings are `artisan.baudrate`, `artisan.motion.default_speed`, `artisan.motion.max_z_speed` and
  `artisan.<head>.laser_offset`. After that the profile counts. A settings value that differs from the profile is
  only noted in the protocol log.
- The machine reads the profile again on every connect, so an edited profile takes effect on the next connect.
- A profile is checked completely. If one value is wrong, the whole profile is **not used**: the controller warns on
  connect and keeps the values from the settings, which are the v2.0 values.

## Layout

```json
{
  "name": "Snapmaker Artisan",
  "gcode":   { "...": "BildHatcher's profile fields (header, footer, laser_modes, burn_power, feedrate, ...)" },
  "machine": { "...": "this document" }
}
```

BildHatcher 2.x profiles have no `gcode` section; their fields sit on the top level. The controller reads that layout
too and treats the top-level fields as the `gcode` section. If you add a `machine` key to a BildHatcher profile,
BildHatcher logs it as an unknown key and ignores it, so one file can serve both programs until v3.0. In v3.0 the
shared package moves BildHatcher's fields into `gcode` (decision 2026-11-24 (5): no BildHatcher change before).

## `machine` section

| Key | Required | Meaning | Used for |
|---|---|---|---|
| `id` | yes | machine id, e.g. `snapmaker_artisan` | J-code header `JH machine=` (P3.2), run log |
| `controller` | no | firmware family, `marlin` | information (the galvo machine will differ, v3.0) |
| `baudrate` | no | serial speed | connect |
| `work_area` | yes | `{"x": [min, max], "y": [...], "z": [...]}` in mm, machine coordinates after homing | preflight and manual moves (P2.5) |
| `limits.max_power_s`, `limits.max_power_p` | no | allowed `S` and `P` values (255, 100) | preflight |
| `limits.max_feed` | no | mm/min, `null` = not checked | preflight |
| `limits.default_speed`, `limits.max_z_speed` | no | mm/s for travel moves and Z | moves |
| `toolheads.<head>.laser_offset` | yes | `[x, y, z]` mm from the camera crosshair to the laser spot | every job, bounding box |
| `toolheads.<head>.m1006_lines` | no | number of lines of the `M1006` answer that identifies this head (C7) | head detection |
| `toolheads.<head>.name` | no | shown text | information |
| `laser_off` | yes, not empty | lines that switch the laser off | every stop, error, pause and job end (safety rule) |
| `outputs.<name>` | no | `{"on": [line], "off": [line]}` for `crosshair`, `light`, `fan`, `air_assist` | buttons |
| `notes` | no | free text | – |

The head names (`laser1064`, `laser455`) are the names the J-code header (`JH toolhead=`) and the run log use.

The rotary stages are the lab's own hardware (C8), with their own port, servo mode and gear ratio. They stay in the
settings (`rotary_motors.*`).
