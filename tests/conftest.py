"""Shared test fixtures: the real ArtisanController / ProcessHandler on a simulated Artisan (no hardware)."""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MACHINECONTROL_USER_DIR", tempfile.mkdtemp(prefix="machinecontrol_user_"))  # keep tests out of ~/Documents

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import pytest  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

import Artisan_Controller  # noqa: E402
import Process_Handler  # noqa: E402
from Settings_Manager import SettingsManager  # noqa: E402
from sim_artisan import FakeRotMotors, FakeSerial, SimArtisan  # noqa: E402

FIXTURES = TESTS / "fixtures"


class _AnswerHoming:
    """Replaces the QMessageBox in ArtisanController.connect(): answers the homing question with Yes."""
    StandardButton = QMessageBox.StandardButton

    def question(self, *args):
        return QMessageBox.StandardButton.Yes


def make_artisan(monkeypatch, sim):
    monkeypatch.setattr(Artisan_Controller.serial, "Serial", lambda *a, **k: FakeSerial(sim, *a, **k))
    monkeypatch.setattr(Artisan_Controller, "QMessageBox", _AnswerHoming)
    settings = SettingsManager(default_settings_path=FIXTURES / "settings.json")
    controller = Artisan_Controller.ArtisanController(settings=settings)
    controller.connect()
    return controller


@pytest.fixture
def sim():
    return SimArtisan()


@pytest.fixture
def artisan(monkeypatch, sim):
    controller = make_artisan(monkeypatch, sim)
    yield controller
    controller.connected = False  # stops the tracking thread without disconnect()'s 1.5 s sleep
    time.sleep(0.15)


@pytest.fixture
def process_handler(monkeypatch, sim, artisan):
    monkeypatch.setattr(Process_Handler, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))  # skip settle sleeps
    return Process_Handler.ProcessHandler(None, artisan, FakeRotMotors(sim))
