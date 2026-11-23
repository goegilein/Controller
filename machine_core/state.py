"""Explicit machine state with allowed transitions (REVISION_PLAN.md P2.1, rule 4).

    disconnected -> connecting -> idle <-> busy (homing, jogging, moving)
                                  idle  -> running <-> paused -> idle
    any connected state -> error -> (user acknowledges) idle
    any connected state -> estop -> disconnected (the firmware needs a restart)

Nothing leaves error / estop on its own and there is no way from error or paused-after-error back to running:
after an error the user decides (safety rule "never resume automatically").
"""
import threading
from enum import Enum


class MachineState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    BUSY = "busy"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    ESTOP = "estop"


S = MachineState
_CONNECTED = {S.CONNECTING, S.IDLE, S.BUSY, S.RUNNING, S.PAUSED, S.ERROR}

ALLOWED = {
    S.DISCONNECTED: {S.CONNECTING},
    S.CONNECTING: {S.IDLE, S.ERROR, S.DISCONNECTED},
    S.IDLE: {S.BUSY, S.RUNNING, S.DISCONNECTED},
    S.BUSY: {S.IDLE},
    S.RUNNING: {S.PAUSED, S.IDLE},
    S.PAUSED: {S.RUNNING, S.IDLE},
    S.ERROR: {S.IDLE, S.DISCONNECTED},
    S.ESTOP: {S.DISCONNECTED},
}
for _state in _CONNECTED:
    ALLOWED[_state] = ALLOWED[_state] | {S.ERROR, S.ESTOP, S.DISCONNECTED}
ALLOWED[S.ERROR] -= {S.ERROR}


class InvalidTransition(Exception):
    pass


class StateMachine:
    """Thread-safe current state; listeners are called with (new_state, reason) outside the lock."""

    def __init__(self, listener=None):
        self._state = S.DISCONNECTED
        self._lock = threading.Lock()
        self._listener = listener

    @property
    def state(self) -> MachineState:
        return self._state

    def can(self, new: MachineState) -> bool:
        return new in ALLOWED[self._state]

    def to(self, new: MachineState, reason: str = ""):
        with self._lock:
            if new not in ALLOWED[self._state]:
                raise InvalidTransition(f"{self._state.value} -> {new.value}")
            self._state = new
        if self._listener:
            self._listener(new, reason)
