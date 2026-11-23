# Machine Control – notes for every session

Read these first:

1. [MachineControl_revision_notes.md](MachineControl_revision_notes.md) – rules, safety, architecture, J-code.
2. [REVISION_PLAN.md](REVISION_PLAN.md) – current status, task IDs, open questions, work log.

Key points:

- Talk with the user in German; code, UI texts, commits and docs in English.
- The Snapmaker Artisan (Marlin over USB serial) is in production. Any change to what is sent to the machine
  is discussed with the user first and listed in REVISION_PLAN.md.
- Work on branch `revision_2.0`; task IDs in commit messages; update the plan in the same commit; push after
  every step; merge to `main` only via PR when the user says so.
- Small, minimal changes. Tests: `python -m pytest` (no hardware needed).
