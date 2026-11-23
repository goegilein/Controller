"""Marlin line protocol (REVISION_PLAN.md P2.2): one reader thread, strict ack matching, timeouts.

- `send(line, timeout)` writes one line and returns the answer lines up to and including its `ok` – one line in
  flight (C3). Marlin acknowledges a move when it is queued, so the planner stays full while we stream.
- Every answer belongs to exactly one command (fixes B03): a stray `ok` found before sending is logged and dropped.
- `Error:` lines raise FirmwareError, a missing `ok` raises AckTimeout, a lost connection raises ConnectionLost –
  the caller (worker / job runner) stops the job safely; nothing here is swallowed (B02).
- `busy:` keep-alive lines extend the deadline.
- `write_now(line)` writes immediately without waiting for an ack and without the send lock – the shortest path for
  stop / emergency stop (B04), even while another thread waits for an `ok`.
No Qt.
"""
import queue
import threading
import time

import protocol_log
from machine_core.transport import TransportClosed

_CLOSED = object()


class MarlinError(Exception):
    pass


class AckTimeout(MarlinError):
    pass


class FirmwareError(MarlinError):
    pass


class ConnectionLost(MarlinError):
    pass


class SendsBlocked(Exception):
    """A stop was written; normal sends are refused until `unblock()` (not an error)."""


def is_ok(line: str) -> bool:
    return line == "ok" or line.startswith("ok ")


class MarlinConnection:
    def __init__(self, transport, device="artisan", on_unsolicited=None):
        self.transport = transport
        self.device = device
        self.on_unsolicited = on_unsolicited  # called with lines that belong to no command
        self.lost = None                      # reason, once the connection is gone
        self._blocked = False                 # set by stop(): no line may follow the stop lines
        self._lines = queue.Queue()
        self._send_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, name=f"{device}-reader", daemon=True)
        self._reader.start()

    # ------------------------------------------------------------------ reading
    def _read_loop(self):
        while self.lost is None:
            try:
                line = self.transport.read_line()
            except TransportClosed as e:
                self._mark_lost(f"connection lost: {e}")
                break
            if line:
                protocol_log.received(self.device, line)
                self._lines.put(line)
        self._lines.put(_CLOSED)

    def _mark_lost(self, reason):
        if self.lost is None:
            self.lost = reason
            protocol_log.note(self.device, reason)

    def _drain_stale(self):
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return
            if line is _CLOSED:
                self._lines.put(_CLOSED)
                return
            if is_ok(line):
                protocol_log.note(self.device, "stray 'ok' dropped")
            elif self.on_unsolicited:
                self.on_unsolicited(line)

    # ------------------------------------------------------------------ writing
    def _write(self, line, bypass_block=False):
        with self._write_lock:
            if self._blocked and not bypass_block:
                raise SendsBlocked(line)
            protocol_log.sent(self.device, line)
            try:
                self.transport.write_line(line)
            except TransportClosed as e:
                self._mark_lost(f"connection lost: {e}")
                raise ConnectionLost(self.lost) from e

    def send(self, line: str, timeout: float = 10.0) -> list:
        with self._send_lock:
            if self.lost:
                raise ConnectionLost(self.lost)
            self._drain_stale()
            self._write(line)
            answer = []
            deadline = time.monotonic() + timeout
            while True:
                try:
                    got = self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    protocol_log.note(self.device, f"timeout: no 'ok' for {line!r} within {timeout} s")
                    raise AckTimeout(f"no acknowledgement for {line!r} within {timeout} s") from None
                if got is _CLOSED:
                    self._lines.put(_CLOSED)
                    raise ConnectionLost(self.lost)
                answer.append(got)
                if is_ok(got):
                    return answer
                if got.startswith("Error"):
                    raise FirmwareError(f"{got} (after {line!r})")
                if got.startswith(("busy:", "echo:busy")):
                    deadline = time.monotonic() + timeout

    def write_now(self, line: str):
        """Write without waiting for an ack and without the send lock (laser off, emergency stop)."""
        self._write(line, bypass_block=True)

    def stop(self, lines):
        """Write `lines` at once and refuse every normal send until `unblock()`.

        Taken under the write lock, so no line of a sender that is just about to write can slip in behind the stop.
        """
        with self._write_lock:
            self._blocked = True
        for line in lines:
            self._write(line, bypass_block=True)

    def unblock(self):
        with self._write_lock:
            self._blocked = False
        self._drain_stale()

    def close(self):
        self._mark_lost("closed by host")
        try:
            self.transport.close()
        except Exception as e:  # closing a vanished port must not hide the reason we close it
            protocol_log.note(self.device, f"close failed: {e!r}")
