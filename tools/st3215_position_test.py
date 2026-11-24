"""C16 hardware test: ST3215 multi-turn absolute position mode (REVISION_PLAN.md C16, HARDWARE_CHECKLIST item 20).

Answers what the register map does not say, before `rotary_motors.control_mode = "position"` is used in production:
  1. Does mode 0 with both angle limits 0 and phase bit 4 report the full (multi-turn, signed) angle?
  2. Does the servo reach goals on the tick: ±1, ±2, ±3, ±10 ticks, 1 / 3 / 5 motor turns, and back?
  3. Does a new goal during a move take over at once (stop = goal := present position)?
  4. Does the servo finish and hold its goal when the PC goes away in the middle of a move (port closed)?
  5. Does the position survive a reconnect, and what is reported after a power cycle (manual step at the end)?

Run with the stage free to turn (no part, no cables in the way), one motor at a time:
    python tools/st3215_position_test.py COM5 --id 1 [--turns 5] [--speed 1000] [--keep]
The registers changed (mode 33, angle limits 9-12, phase 18) are saved to st3215_backup_<id>.json first and written
back at the end, unless --keep. Every reading goes to st3215_test_<id>_<time>.csv. Nothing here talks to the laser.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libraries.scservo_sdk import COMM_SUCCESS, PortHandler, sms_sts  # noqa: E402

TICKS = 4096
REG = {"min_angle": 9, "max_angle": 11, "phase": 18, "cw_dead": 26, "ccw_dead": 27, "offset": 31, "mode": 33}
FULL_ANGLE = 0x10


class Servo:
    def __init__(self, port, sid):
        self.port = PortHandler(port)
        if not self.port.openPort():
            sys.exit(f"cannot open {port}")
        self.d = sms_sts(self.port)
        self.sid = sid
        if self.d.ping(sid)[1] != COMM_SUCCESS:
            sys.exit(f"no servo with id {sid} on {port}")

    def read1(self, reg):
        value, result, _ = self.d.read1ByteTxRx(self.sid, reg)
        return value if result == COMM_SUCCESS else None

    def read2(self, reg):
        value, result, _ = self.d.read2ByteTxRx(self.sid, reg)
        return value if result == COMM_SUCCESS else None

    def pos(self):
        value, result, _ = self.d.ReadPos(self.sid)
        return value if result == COMM_SUCCESS else None

    def moving(self):
        value, result, _ = self.d.ReadMoving(self.sid)
        return value if result == COMM_SUCCESS else None

    def goal(self, ticks, speed, acc=50):
        result, _ = self.d.WritePosEx(self.sid, self.d.scs_toscs(int(ticks), 15), speed, acc)
        return result == COMM_SUCCESS

    def eeprom(self, writes):
        self.d.unLockEprom(self.sid)
        for reg, value, size in writes:
            (self.d.write2ByteTxRx if size == 2 else self.d.write1ByteTxRx)(self.sid, reg, value)
        self.d.LockEprom(self.sid)

    def close(self):
        self.port.closePort()


def snapshot(servo):
    return {"mode": servo.read1(REG["mode"]), "min_angle": servo.read2(REG["min_angle"]),
            "max_angle": servo.read2(REG["max_angle"]), "phase": servo.read1(REG["phase"]),
            "cw_dead": servo.read1(REG["cw_dead"]), "ccw_dead": servo.read1(REG["ccw_dead"]),
            "offset": servo.read2(REG["offset"])}


def settle(servo, log, label, timeout=30.0):
    """Wait until the servo stands still (moving flag 0 and the same position for 10 readings)."""
    t0, last, same = time.monotonic(), None, 0
    while time.monotonic() - t0 < timeout:
        p, mv = servo.pos(), servo.moving()
        log(label, p, mv)
        same = same + 1 if p == last and mv == 0 else 0
        last = p
        if same >= 10:
            return p, time.monotonic() - t0
        time.sleep(0.02)
    return last, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--turns", type=int, default=5, help="largest move in motor turns (5 = 360° at 5:1)")
    ap.add_argument("--speed", type=int, default=1000, help="ticks/s (v1.0 speed limit 1000)")
    ap.add_argument("--keep", action="store_true", help="leave the servo in position mode")
    args = ap.parse_args()

    servo = Servo(args.port, args.id)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = Path(f"st3215_backup_{args.id}.json")
    before = snapshot(servo)
    if not backup_path.exists():                       # keep the very first backup if the test is run again
        backup_path.write_text(json.dumps(before, indent=2), encoding="utf-8")
    print("registers before:", before)
    if input("The stage will turn up to %d motor turns in both directions. Type 'yes': " % args.turns) != "yes":
        return

    out = open(f"st3215_test_{args.id}_{stamp}.csv", "w", newline="", encoding="utf-8")
    rows = csv.writer(out)
    rows.writerow(["time", "step", "present", "moving"])
    t_start = time.monotonic()

    def log(step, p, mv):
        rows.writerow([f"{time.monotonic() - t_start:.3f}", step, p, mv])

    results = []

    def report(name, ok, detail):
        results.append((name, ok, detail))
        print(f"[{'OK ' if ok else 'BAD'}] {name}: {detail}")

    try:
        # --- 1. multi-turn absolute mode and feedback
        servo.d.EnableTorque(args.id, 0)               # no jump to an old goal while switching
        servo.eeprom([(REG["mode"], 0, 1), (REG["min_angle"], 0, 2), (REG["max_angle"], 0, 2),
                      (REG["phase"], (before["phase"] or 0) | FULL_ANGLE, 1)])
        servo.goal(servo.pos(), 0)
        servo.d.EnableTorque(args.id, 1)
        after = snapshot(servo)
        report("registers written", after["mode"] == 0 and after["min_angle"] == 0 and after["max_angle"] == 0
               and (after["phase"] or 0) & FULL_ANGLE, str(after))
        start, _ = settle(servo, log, "start")
        servo.goal(start, args.speed)                   # hold where it is
        print("start position", start)

        # --- 2. accuracy: small steps and whole turns, each relative to the start
        moves = [1, 2, 3, 0, -1, -2, -3, 0, 10, -10, 0, TICKS, 0, 3 * TICKS]
        moves += [args.turns * TICKS, 0, -TICKS, -args.turns * TICKS, 0] if args.turns > 3 else [0, -TICKS, 0]
        max_abs = 0
        for delta in moves:
            target = start + delta
            servo.goal(target, args.speed)
            p, took = settle(servo, log, f"goal {delta:+d}")
            err = None if p is None else p - target
            max_abs = max(max_abs, abs(err) if err is not None else 99)
            report(f"goal {delta:+6d} ticks", err is not None and abs(err) <= 1,
                   f"present {p}, error {err} ticks, {took and round(took, 2)} s")
        report("full-angle feedback", max_abs <= 1 and args.turns >= 1,
               "positions beyond 0..4095 were reported" if max_abs <= 1 else "see the errors above")

        # --- 3. stop in the middle of a move
        servo.goal(start + 2 * TICKS, args.speed)
        time.sleep(0.5)
        p = servo.pos()
        servo.goal(p, args.speed)
        stop, _ = settle(servo, log, "stop")
        report("stop (goal := present)", stop is not None and abs(stop - p) < 0.2 * args.speed,
               f"stopped at {stop}, {None if stop is None else stop - p} ticks after the stop command")
        servo.goal(start, args.speed)
        settle(servo, log, "back")

        # --- 4. PC gone in the middle of a move
        servo.goal(start + TICKS, args.speed)
        time.sleep(0.2)
        servo.close()
        time.sleep(5)
        servo = Servo(args.port, args.id)
        p, _ = settle(servo, log, "after reconnect")
        report("finishes and holds without the PC", p is not None and abs(p - (start + TICKS)) <= 1,
               f"present {p}, goal {start + TICKS}")
        servo.goal(start, args.speed)
        settle(servo, log, "back")
    finally:
        out.close()
        if not args.keep:
            servo.d.EnableTorque(args.id, 0)
            # angle limits back first, then the mode (mode 0 with limits 0..4095 = the factory single-turn mode)
            servo.eeprom([(REG["min_angle"], before["min_angle"] or 0, 2),
                          (REG["max_angle"], before["max_angle"] if before["max_angle"] is not None else 4095, 2),
                          (REG["phase"], before["phase"] or 0, 1), (REG["mode"], before["mode"] or 0, 1)])
            print("registers restored:", snapshot(servo))
        servo.close()

    print("\nSummary")
    for name, ok, detail in results:
        print(f"  {'OK ' if ok else 'BAD'} {name}: {detail}")
    print("\n5. Manual: switch the servo power off and on, run again with --turns 1 and note the start position "
          "(does the multi-turn count survive a power cycle?).")
    print("Send st3215_test_*.csv and this output back.")


if __name__ == "__main__":
    main()
