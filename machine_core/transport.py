"""Line transports to a machine: the real serial port and the simulated Artisan (REVISION_PLAN.md P2.2).

Interface: write_line(str), read_line() -> str ("" if nothing arrived within a short poll), close().
Both raise TransportClosed when the connection is gone (cable pulled, port closed).
"""
import serial

from machine_core.sim import SimArtisan, SimDisconnected


class TransportClosed(Exception):
    pass


class SerialTransport:
    def __init__(self, port: str, baudrate: int = 115200):
        try:
            self._ser = serial.Serial(port, baudrate, timeout=0.05, write_timeout=2)
        except serial.SerialException as e:
            raise TransportClosed(str(e)) from e
        self.name = port

    def write_line(self, line: str):
        try:
            self._ser.write((line + "\n").encode("ascii"))
        except (serial.SerialException, OSError) as e:
            raise TransportClosed(str(e)) from e

    def read_line(self) -> str:
        try:
            return self._ser.readline().decode("ascii", errors="replace").strip()
        except (serial.SerialException, OSError, TypeError) as e:  # pyserial raises TypeError when the port vanishes
            raise TransportClosed(str(e)) from e

    def close(self):
        self._ser.close()


class SimTransport:
    """The virtual machine. `sim` is a machine_core.sim.SimArtisan (realtime mode for dry runs)."""

    def __init__(self, sim: SimArtisan = None):
        self.sim = sim or SimArtisan(realtime=True)
        self.name = "simulator"
        self._closed = False

    def write_line(self, line: str):
        if self._closed:
            raise TransportClosed("closed")
        try:
            self.sim.receive(line)
        except SimDisconnected as e:
            raise TransportClosed("simulated cable pulled") from e

    def read_line(self) -> str:
        if self._closed:
            raise TransportClosed("closed")
        try:
            return self.sim.readline(wait=0.05)
        except SimDisconnected as e:
            raise TransportClosed("simulated cable pulled") from e

    def close(self):
        self._closed = True
        self.sim.close()
