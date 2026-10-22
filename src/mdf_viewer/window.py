"""Application coordination; parser operations are queued to the file worker."""

from pathlib import Path

from PySide6.QtCore import QMetaObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QProgressBar, QSplitter, QToolBar,
)

from .browser import SignalBrowser
from .worker import FileWorker
from .workspace import WaveformWorkspace


class MainWindow(QMainWindow):
    request_open = Signal(int, str)
    request_channel = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MDF Waveform Viewer")
        self.resize(1440, 940)
        self.session = 0
        self._request_id = 0
        self.opening = False
        self.pending: dict[tuple[int, object], set] = {}
        self.browser = SignalBrowser()
        self.workspace = WaveformWorkspace()
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.browser)
        split.addWidget(self.workspace)
        split.setSizes([390, 1050])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        toolbar = QToolBar("Recording and waveforms")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_action = QAction("Open MDF…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_file)
        toolbar.addAction(self.open_action)
        add_action = QAction("Add waveform panel", self)
        add_action.setShortcut("Ctrl+N")
        add_action.triggered.connect(self.workspace.add_panel)
        toolbar.addAction(add_action)
        fit_action = QAction("Fit all panels", self)
        fit_action.setShortcut("Ctrl+0")
        fit_action.triggered.connect(self.workspace.fit_all)
        toolbar.addAction(fit_action)
        toolbar.addSeparator()
        self.sync = QCheckBox("Synchronize time axes")
        self.sync.setChecked(True)
        self.sync.toggled.connect(self.workspace.set_synchronized)
        toolbar.addWidget(self.sync)
        self.file_label = QLabel("  No recording open")
        toolbar.addWidget(self.file_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(140)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Open a recording, select a panel, then add signals from the browser.")
        self.browser.add_requested.connect(self.add_channels)
        self.workspace.channels_dropped.connect(self._drop_channels)
        self.workspace.selection_changed.connect(self._target_changed)
        self.workspace.traces_changed.connect(self._update_usage)
        self.thread = QThread(self)
        self.worker = FileWorker()
        self.worker.moveToThread(self.thread)
        self.request_open.connect(self.worker.open)
        self.request_channel.connect(self.worker.load)
        self.worker.opened.connect(self._opened)
        self.worker.loaded.connect(self._loaded)
        self.worker.failed.connect(self._failed)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        self._target_changed(self.workspace.active)

    @Slot()
    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open measurement recording", "", "MDF recordings (*.mf4 *.mdf *.dat);;All files (*)"
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str):
        if self.opening:
            return
        self._request_id += 1
        self.opening = True
        self.open_action.setEnabled(False)
        self.browser.setEnabled(False)
        self.statusBar().showMessage(f"Opening {Path(path).name}…")
        self._update_progress()
        self.request_open.emit(self._request_id, str(path))

    @Slot(int, str, object)
    def _opened(self, session, path, channels):
        self.session = session
        self.pending.clear()
        self.workspace.reset()
        self.browser.set_channels(channels)
        self.file_label.setText(f"  {Path(path).name}")
        self.file_label.setToolTip(path)
        self.setWindowTitle(f"{Path(path).name} — MDF Waveform Viewer")
        self._finish_open()
        self.statusBar().showMessage(f"Loaded {len(channels):,} measurement channels. Select signals to plot.")

    def _finish_open(self):
        self.opening = False
        self.open_action.setEnabled(True)
        self.browser.setEnabled(True)
        self._update_progress()

    @Slot(object)
    def add_channels(self, keys):
        if self.opening or not self.session:
            return
        panel = self.workspace.active or self.workspace.add_panel()
        for key in keys:
            if key in panel.traces:
                continue
            token = (self.session, key)
            if token not in self.pending:
                self.pending[token] = {panel}
                self.request_channel.emit(self.session, key)
            else:
                self.pending[token].add(panel)
        self._update_progress()
        if self.pending:
            self.statusBar().showMessage(f"Loading {len(self.pending)} channel(s)…")

    @Slot(object, object)
    def _drop_channels(self, panel, mime):
        if self.opening or panel not in self.workspace.panels:
            return
        if mime.source_model is not self.browser.model:
            return
        keys = mime.keys()
        if keys:
            self.workspace.select(panel)
            self.add_channels(keys)

    @Slot(int, object, object)
    def _loaded(self, session, key, data):
        targets = self.pending.pop((session, key), set())
        if session == self.session and not self.opening:
            for panel in targets:
                if panel in self.workspace.panels:
                    panel.add_signal(data)
            self.statusBar().showMessage(f"Loaded {data.info.label}")
        self._update_progress()

    @Slot(int, str, object, str)
    def _failed(self, session, operation, key, message):
        if operation == "open":
            self._finish_open()
            title = "Cannot open recording"
        else:
            self.pending.pop((session, key), None)
            self._update_progress()
            if session != self.session or self.opening:
                return
            title = "Cannot plot channel"
        self.statusBar().showMessage(f"{title}: {message}")
        # Non-modal: parsing other channels and normal navigation can continue.
        dialog = QMessageBox(QMessageBox.Icon.Warning, title, message, parent=self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _target_changed(self, panel):
        name = panel.title.text() if panel else "a new panel will be created when you add signals"
        self.browser.target.setText(f"Target: {name}")

    def _update_usage(self):
        usage = {}
        for panel in self.workspace.panels:
            for key, trace in panel.traces.items():
                assigned, visible = usage.get(key, (0, 0))
                usage[key] = assigned + 1, visible + int(trace.curve.isVisible())
        self.browser.model.set_usage(usage)

    def _update_progress(self):
        self.progress.setVisible(self.opening or bool(self.pending))

    def closeEvent(self, event):
        # Queue cleanup after any in-flight parser operation. Never terminate a
        # thread while it owns a file. Keep the event loop alive during shutdown.
        if self.thread.isRunning():
            if self.opening or self.pending:
                self.statusBar().showMessage("Waiting for file operations before closing…")
                event.ignore()
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self.close)
                return
            QMetaObject.invokeMethod(self.worker, "close", Qt.ConnectionType.BlockingQueuedConnection)
            self.thread.quit()
            self.thread.wait()
        for panel in self.workspace.panels:
            panel.dispose()
        event.accept()
