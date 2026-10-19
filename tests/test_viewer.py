import threading

import numpy as np
from PySide6.QtCore import QItemSelectionModel, QPoint, QTimer, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import key_named


def add(window, qtbot, names, panel=None):
    if panel:
        window.workspace.select(panel)
    keys = [key_named(window, name) for name in names]
    window.add_channels(keys)
    qtbot.waitUntil(lambda: not window.pending, timeout=10000)
    return keys


def test_search_multiadd_hide_remove_and_reorder(window, qtbot):
    browser = window.browser
    browser.search.setText("phase")
    assert browser.proxy.rowCount() == 3
    for row in range(3):
        browser.table.selectionModel().select(
            browser.proxy.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    qtbot.mouseClick(browser.add_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not window.pending, timeout=10000)
    first = window.workspace.active
    assert len(first.traces) == 3
    assert len(first.plot.plotItem.legend.items) == 3
    key = next(iter(first.traces))
    first.traces[key].row.setCheckState(0, Qt.CheckState.Unchecked)
    assert not first.traces[key].curve.isVisible()
    assert browser.model.usage[key] == (1, 0)
    first.traces[key].row.setCheckState(0, Qt.CheckState.Checked)
    assert browser.model.usage[key] == (1, 1)
    second = window.workspace.add_panel()
    add(window, qtbot, ["Duty Cycle"], second)
    window.workspace.move_panel(second, -1)
    assert window.workspace.panels == [second, first]
    first.remove_signal(key)
    assert len(first.traces) == 2
    assert len(first.plot.plotItem.legend.items) == 2
    window.workspace.remove_panel(first)
    assert window.workspace.active is second
    assert len(second.traces) == 1
    assert second.minimumHeight() > 0


def test_sync_independent_navigation_and_fit(window, qtbot):
    first = window.workspace.active
    add(window, qtbot, ["DC Bus Voltage"], first)
    second = window.workspace.add_panel()
    add(window, qtbot, ["Duty Cycle"], second)
    first.plot.setXRange(2.5, 3, padding=0)
    np.testing.assert_allclose(first.plot.viewRange()[0], second.plot.viewRange()[0])
    qtbot.mouseClick(window.sync, Qt.MouseButton.LeftButton)
    first.plot.setXRange(1, 1.5, padding=0)
    np.testing.assert_allclose(second.plot.viewRange()[0], [2.5, 3])
    qtbot.mouseClick(window.sync, Qt.MouseButton.LeftButton)
    np.testing.assert_allclose(first.plot.viewRange()[0], second.plot.viewRange()[0])
    window.workspace.fit_all()
    assert first.plot.viewRange()[0][0] <= 0
    assert first.plot.viewRange()[0][1] >= 4.999
    first.auto_y.setChecked(False)
    first.plot.setXRange(2.51, 2.6, padding=0)
    first.fit_y_visible()
    low, high = first.plot.viewRange()[1]
    assert high < 47  # the bus transient lies near 44 V, outside it near 48 V
    assert low > 40
    assert second.plot.viewRange()[1] != first.plot.viewRange()[1]


def test_mouse_wheel_zoom_and_drag_pan(window, qtbot):
    panel = window.workspace.active
    add(window, qtbot, ["DC Bus Voltage"])
    qtbot.wait(50)
    viewport = panel.plot.viewport()
    center = panel.plot.mapFromScene(panel.plot.getViewBox().sceneBoundingRect().center())
    before = panel.plot.viewRange()[0]
    event = QWheelEvent(center, viewport.mapToGlobal(center), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(viewport, event)
    qtbot.wait(50)
    zoomed = panel.plot.viewRange()[0]
    assert zoomed[1] - zoomed[0] < before[1] - before[0]
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseMove(viewport, center + QPoint(60, 0), delay=30)
    qtbot.mouseMove(viewport, center + QPoint(100, 0), delay=30)
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=center + QPoint(100, 0))
    assert not np.allclose(panel.plot.viewRange()[0], zoomed)


def test_switch_file_duplicate_names_invalid_readout_and_empty(window, qtbot, examples):
    add(window, qtbot, ["DC Bus Voltage"])
    old_panel = window.workspace.active
    window.open_file(str(examples / "edge_cases.mf4"))
    qtbot.waitUntil(lambda: not window.opening, timeout=10000)
    assert old_panel not in window.workspace.panels
    assert not window.workspace.active.traces
    assert not window.browser.model.usage
    keys = [channel.key for channel in window.browser.model.channels if channel.name == "Temperature"]
    window.add_channels(keys)
    qtbot.waitUntil(lambda: not window.pending, timeout=10000)
    panel = window.workspace.active
    assert len(panel.traces) == 2
    panel.inspect_at(.105)
    assert panel.traces[keys[0]].row.text(2) == "Invalid / missing"
    assert "K" in panel.traces[keys[1]].row.text(2)
    add(window, qtbot, ["Empty Sensor"])
    panel.inspect_at(0)
    empty = panel.traces[key_named(window, "Empty Sensor")]
    assert empty.row.text(2) == "No samples"
    assert empty.row.text(3) == "Empty channel"
    window.open_file(str(examples / "empty_recording.mf4"))
    qtbot.waitUntil(lambda: not window.opening, timeout=10000)
    assert not window.browser.model.channels
    assert not window.workspace.active.traces


def test_parse_errors_preserve_workspace(window, qtbot, tmp_path, examples):
    add(window, qtbot, ["DC Bus Voltage"])
    panel = window.workspace.active
    bad = tmp_path / "bad.mf4"
    bad.write_bytes(b"not MDF")
    window.open_file(str(bad))
    qtbot.waitUntil(lambda: not window.opening, timeout=10000)
    assert window.workspace.active is panel
    assert len(panel.traces) == 1
    assert window.browser.isEnabled()
    for dialog in window.findChildren(QMessageBox):
        dialog.close()
    window.open_file(str(examples / "edge_cases.mf4"))
    qtbot.waitUntil(lambda: not window.opening, timeout=10000)
    add(window, qtbot, ["Text State"])
    assert not window.workspace.active.traces
    assert window.findChildren(QMessageBox)
    for dialog in window.findChildren(QMessageBox):
        dialog.close()


def test_loading_is_off_thread_and_removed_target_is_ignored(window, qtbot, monkeypatch):
    original = window.worker.manager.load
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_load(key):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return original(key)

    monkeypatch.setattr(window.worker.manager, "load", slow_load)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    target = window.workspace.active
    window.add_channels([key_named(window, "DC Bus Voltage")])
    qtbot.waitUntil(entered.is_set, timeout=5000)
    try:
        qtbot.waitUntil(lambda: len(ticks) >= 3, timeout=1000)
        window.workspace.remove_panel(target)
        replacement = window.workspace.add_panel()
    finally:
        release.set()
        timer.stop()
    qtbot.waitUntil(lambda: not window.pending, timeout=5000)
    assert calls[0] != threading.get_ident()
    assert not replacement.traces


def test_one_loaded_array_shared_by_two_panels(window, qtbot):
    first = window.workspace.active
    add(window, qtbot, ["DC Bus Voltage"], first)
    second = window.workspace.add_panel()
    keys = add(window, qtbot, ["DC Bus Voltage"], second)
    assert first.traces[keys[0]].data is second.traces[keys[0]].data


def test_file_switch_discards_inflight_results(window, qtbot, monkeypatch, examples):
    original = window.worker.manager.load
    entered, release = threading.Event(), threading.Event()

    def slow_load(key):
        entered.set()
        assert release.wait(5)
        return original(key)

    monkeypatch.setattr(window.worker.manager, "load", slow_load)
    old_session = window.session
    old_panel = window.workspace.active
    window.add_channels([key_named(window, "DC Bus Voltage")])
    qtbot.waitUntil(entered.is_set, timeout=5000)
    try:
        window.open_file(str(examples / "edge_cases.mf4"))
        assert not window.browser.isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.opening and not window.pending, timeout=10000)
    assert window.session != old_session
    assert old_panel not in window.workspace.panels
    assert not window.workspace.active.traces
    assert len(window.browser.model.channels) == 5


def test_all_panels_can_be_removed_and_recreated(window, qtbot):
    panel = window.workspace.active
    window.workspace.remove_panel(panel)
    assert window.workspace.active is None
    assert not window.workspace.panels
    add(window, qtbot, ["DC Bus Voltage", "Duty Cycle"])
    assert len(window.workspace.panels) == 1
    panel = window.workspace.active
    assert len(panel.traces) == 2
    assert len({trace.curve.opts['pen'].color().name() for trace in panel.traces.values()}) == 2


def test_fit_y_excludes_samples_outside_time_window(window, qtbot, examples):
    window.open_file(str(examples / "edge_cases.mf4"))
    qtbot.waitUntil(lambda: not window.opening, timeout=10000)
    key = window.browser.model.channels[0].key
    window.add_channels([key])
    qtbot.waitUntil(lambda: not window.pending, timeout=10000)
    panel = window.workspace.active
    panel.auto_y.setChecked(False)
    panel.plot.setXRange(.019, .021, padding=0)
    panel.fit_y_visible()
    low, high = panel.plot.viewRange()[1]
    assert low < 21 < high
    assert high < 22
