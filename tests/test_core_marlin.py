"""P2.2: Marlin protocol against the simulated Artisan – ack matching, timeouts, lost connection, stop path, streaming."""
import threading
import time

import pytest

from machine_core.marlin import AckTimeout, ConnectionLost, FirmwareError, MarlinConnection
from machine_core.sim import SimArtisan
from machine_core.transport import SimTransport


def connect(sim):
    return MarlinConnection(SimTransport(sim))


@pytest.fixture(params=[False, True], ids=["instant", "realtime"])
def sim(request):
    s = SimArtisan(realtime=request.param, speedup=50)
    yield s
    s.close()


def test_every_answer_belongs_to_its_command(sim):
    """B03: the old code left the ok of M114 in the buffer; here M114 and the next command get their own answers."""
    con = connect(sim)
    answer = con.send("M114")
    assert answer[0].startswith("X:0.00 Y:0.00") and answer[-1] == "ok"
    assert con.send("G0 X10 F6000") == ["ok"]
    assert con.send("M114")[0].startswith("X:10.00")
    answer = con.send("M1006")
    assert answer[0] == "Tool Head: LASER" and len(answer) == 39  # one M1006 is enough
    assert con.send("M118 sync_1") == ["sync_1", "ok"]


def test_stray_ok_is_dropped_not_taken_as_ack(sim):
    con = connect(sim)
    sim.extra_lines = lambda line: ["ok"] if line == "M8" else []  # firmware sends one ok too many
    assert con.send("M8") == ["ok"]
    time.sleep(0.1)
    assert con.send("M114")[0].startswith("X:")


def test_missing_ack_raises_instead_of_continuing(sim):
    """B02: a missing ok stops the caller."""
    con = connect(sim)
    sim.drop_ack = lambda line: line.startswith("G1")
    t0 = time.monotonic()
    with pytest.raises(AckTimeout):
        con.send("G1 X5 F600", timeout=0.3)
    assert time.monotonic() - t0 < 1.0


def test_firmware_error_raises(sim):
    con = connect(sim)
    sim.error_reply = lambda line: "Error:Printer halted. kill() called!" if line.startswith("G28") else None
    with pytest.raises(FirmwareError, match="Printer halted"):
        con.send("G28", timeout=1)


def test_busy_lines_are_part_of_the_answer(sim):
    con = connect(sim)
    sim.extra_lines = lambda line: ["busy: processing"] if line.startswith("G28") else []
    assert con.send("G28") == ["busy: processing", "ok"]


def test_cable_pulled_raises_connection_lost(sim):
    con = connect(sim)
    con.send("M114")
    sim.fail_after = len(sim.trace)
    with pytest.raises(ConnectionLost):
        con.send("G0 X1")
    with pytest.raises(ConnectionLost):
        con.send("M114")
    assert con.lost


def test_write_now_bypasses_a_blocked_send(sim):
    """B04: the stop path does not wait for the command lock held by a send that waits for its ok."""
    con = connect(sim)
    sim.drop_ack = lambda line: line.startswith("G1")
    blocked = threading.Thread(target=lambda: pytest.raises(AckTimeout, con.send, "G1 X5 F600", timeout=2), daemon=True)
    blocked.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    con.write_now("M112")
    assert time.monotonic() - t0 < 0.1
    deadline = time.monotonic() + 1
    while not sim.halted and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sim.halted and not sim.laser_armed
    blocked.join(3)


def test_streaming_keeps_the_planner_busy():
    """C3: with one line in flight the head never waits for the host while moves are queued.

    200 hatch segments of 2 mm at 2100 mm/min (57 ms each) stream at 10x speed (5.7 ms per block) – the planner
    must still never run empty between blocks.
    """
    sim = SimArtisan(realtime=True, speedup=10)
    con = connect(sim)
    con.send("G0 X0 Y0 F6000")
    con.send("M400", timeout=5)
    sim.idle_gaps = 0.0
    for i in range(200):
        con.send(f"G1 X{2 * (i + 1)} Y0 S100 F2100")
    con.send("M400", timeout=10)
    assert sim.blocks_executed >= 201
    assert sim.idle_gaps < 0.05, f"planner ran empty for {sim.idle_gaps:.3f} s"
    sim.close()


def test_planner_full_delays_the_ack():
    """Marlin's flow control: with the planner full the ok of the next move only comes when a block is done."""
    sim = SimArtisan(realtime=True, speedup=1, planner_size=2)
    con = connect(sim)
    for x in (10, 20):
        con.send(f"G1 X{x} F6000")  # 0.1 s each
    t0 = time.monotonic()
    con.send("G1 X30 F6000")
    assert time.monotonic() - t0 > 0.05
    sim.close()


def test_m3_standstill_emission_is_visible():
    """C13 worst case: in M3 the simulated laser keeps firing when no more commands come."""
    sim = SimArtisan(realtime=True, speedup=10)
    con = connect(sim)
    con.send("M3 P0")
    con.send("G1 X5 S120 F600")
    con.send("M400", timeout=5)
    time.sleep(0.2)
    assert sim.laser_armed and sim.standstill_emission
    con.send("M5")
    assert not sim.laser_armed
    sim.close()
