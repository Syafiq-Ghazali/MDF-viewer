import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from mdf_viewer.data import MDFDataManager
from mdf_viewer.window import MainWindow


@pytest.fixture
def examples():
    return Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def manager():
    manager = MDFDataManager()
    yield manager
    manager.close()


@pytest.fixture
def window(qtbot, examples):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_file(str(examples / "motor_drive.mf4"))
    qtbot.waitUntil(lambda: not window.opening, timeout=10000)
    assert len(window.browser.model.channels) == 6
    yield window
    qtbot.waitUntil(lambda: not window.pending and not window.opening, timeout=10000)
    window.close()
    assert not window.thread.isRunning()


def key_named(window, name):
    return next(channel.key for channel in window.browser.model.channels if channel.name == name)
