"""Protocol log: every line sent to and received from a machine, with timestamp and thread (REVISION_PLAN.md P0.2).

Rotating file <USER_DIR>/logs/protocol.log. Line format:
    2026-11-23 14:02:11.348 [MainThread] artisan > G0 X10 F1800
    2026-11-23 14:02:11.361 [MainThread] artisan < ok
    2026-11-23 14:02:12.001 [Thread-3 (track_axis)] artisan # timeout waiting for 'ok'
">" sent, "<" received, "#" note (connect, timeouts, exceptions). Pure logging, no Qt.
"""
import logging
from logging.handlers import RotatingFileHandler

from PathManager import USER_DIR

LOG_DIR = USER_DIR / "logs"

_log = logging.getLogger("protocol")
_log.propagate = False  # keep the protocol out of the console / app log
_log.setLevel(logging.INFO)


def setup(log_dir=LOG_DIR):
    """Attach the rotating file handler; returns the log file path or None if the folder is not writable."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        # 20 MB x 10: an idle connection polls M114 at 10 Hz (~7 MB/h), a long job must not rotate its start away
        handler = RotatingFileHandler(log_dir / "protocol.log", maxBytes=20_000_000, backupCount=10, encoding="utf-8")
    except OSError as e:
        logging.getLogger(__name__).warning("Protocol log disabled, cannot write to %s: %s", log_dir, e)
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d [%(threadName)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    _log.addHandler(handler)
    return log_dir / "protocol.log"


def sent(device, line):
    _log.info("%s > %s", device, line)


def received(device, line):
    _log.info("%s < %s", device, line)


def note(device, text):
    _log.info("%s # %s", device, text)
