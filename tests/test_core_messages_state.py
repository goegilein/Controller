"""P2.1: messages round-trip through JSON, state transitions follow the safety rules."""
import pytest

from machine_core import messages as m
from machine_core.state import ALLOWED, InvalidTransition, MachineState as S, StateMachine

SAMPLES = [
    m.Connect("COM7"), m.Disconnect(), m.Home("Z"), m.Jog("X", -0.5, 20), m.JogStart("Y", 1, 10), m.JogStop(),
    m.MoveTo(1, 2, 3, speed=30, frame="work"), m.SetWorkPosition(), m.SetOutput("air_assist", True),
    m.StartJob("C:/jobs/a.jcode"), m.Pause(), m.Resume(), m.Stop(), m.EmergencyStop(), m.AcknowledgeError(),
    m.StateChanged("running", "job started"), m.PositionChanged((1.0, 2.0, 3.0), (11.0, 12.0, 13.0)),
    m.ToolheadDetected("laser1064", (21.3, -11.3, 0)), m.JobProgress(1, 2, 33.5), m.LogLine("hi", "warning"),
    m.ErrorRaised("ack timeout", "timeout"),
]


@pytest.mark.parametrize("message", SAMPLES, ids=lambda x: type(x).__name__)
def test_json_round_trip(message):
    assert m.from_json(m.to_json(message)) == message


def test_happy_path():
    seen = []
    sm = StateMachine(lambda state, reason: seen.append(state))
    for state in (S.CONNECTING, S.IDLE, S.BUSY, S.IDLE, S.RUNNING, S.PAUSED, S.RUNNING, S.IDLE, S.DISCONNECTED):
        sm.to(state)
    assert seen[-1] == S.DISCONNECTED and len(seen) == 9


@pytest.mark.parametrize("start", [S.ERROR, S.ESTOP, S.DISCONNECTED])
def test_never_resume_into_a_job(start):
    assert S.RUNNING not in ALLOWED[start] and S.PAUSED not in ALLOWED[start]


def test_error_needs_acknowledge_and_estop_needs_reconnect():
    assert ALLOWED[S.ERROR] == {S.IDLE, S.ESTOP, S.DISCONNECTED}
    assert ALLOWED[S.ESTOP] == {S.DISCONNECTED}


@pytest.mark.parametrize("state", [S.CONNECTING, S.IDLE, S.BUSY, S.RUNNING, S.PAUSED, S.ERROR])
def test_estop_and_error_reachable_from_every_connected_state(state):
    assert S.ESTOP in ALLOWED[state]
    assert state == S.ERROR or S.ERROR in ALLOWED[state]


def test_invalid_transition_raises_and_keeps_state():
    sm = StateMachine()
    with pytest.raises(InvalidTransition):
        sm.to(S.RUNNING)
    assert sm.state == S.DISCONNECTED
