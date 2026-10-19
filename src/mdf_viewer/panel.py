"""One interactive plot, with per-signal visibility and recorded-sample readout."""

from dataclasses import dataclass
from html import escape

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from .data import ChannelData, ChannelKey


@dataclass
class Trace:
    data: ChannelData
    curve: pg.PlotDataItem
    row: QTreeWidgetItem


def trace_color(index: int) -> QColor:
    palette = ("#55c9ff", "#ffb454", "#73e2a7", "#f28cce", "#b4a1ff", "#ffe27a")
    if index < len(palette):
        return QColor(palette[index])
    return QColor.fromHsvF((index * 0.61803398875) % 1, 0.62, 1.0)


class WaveformPanel(QFrame):
    selected = Signal(object)
    remove_requested = Signal(object)
    move_requested = Signal(object, int)
    traces_changed = Signal()
    renamed = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("waveformPanel")
        self.setMinimumHeight(360)
        self.traces: dict[ChannelKey, Trace] = {}
        self._color_index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        header = QHBoxLayout()
        self.select_button = QPushButton("Select")
        self.select_button.setFixedWidth(80)
        self.select_button.clicked.connect(lambda: self.selected.emit(self))
        self.title = QLineEdit(title)
        self.title.setToolTip("Rename this waveform panel")
        self.title.textChanged.connect(self.renamed)
        self.title.selectionChanged.connect(lambda: self.selected.emit(self))
        header.addWidget(self.select_button)
        header.addWidget(self.title, 1)
        for text, tip, callback in (
            ("↑", "Move panel up", lambda: self.move_requested.emit(self, -1)),
            ("↓", "Move panel down", lambda: self.move_requested.emit(self, 1)),
            ("Remove panel", "Remove this waveform panel", lambda: self.remove_requested.emit(self)),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            header.addWidget(button)
        layout.addLayout(header)
        tools = QHBoxLayout()
        fit = QPushButton("Fit time + Y")
        fit.clicked.connect(self.fit_all)
        fit_y = QPushButton("Fit Y to visible time")
        fit_y.clicked.connect(self.fit_y_visible)
        self.auto_y = QCheckBox("Auto Y")
        self.auto_y.setChecked(True)
        self.auto_y.toggled.connect(self._auto_y_changed)
        tools.addWidget(fit)
        tools.addWidget(fit_y)
        tools.addWidget(self.auto_y)
        tools.addStretch()
        layout.addLayout(tools)
        self.plot = pg.PlotWidget(background="#101923")
        self.plot.setMinimumHeight(140)
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.setLabel("left", "Value")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.addLegend(offset=(12, 8))
        self.plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.plot.getViewBox().sigRangeChangedManually.connect(self._manual_range)
        self.plot.scene().sigMouseClicked.connect(lambda *_: self.selected.emit(self))
        self.cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#8c9dae", style=Qt.PenStyle.DashLine))
        self.plot.addItem(self.cursor, ignoreBounds=True)
        self.cursor.hide()
        # Rate-limit readouts; curve navigation uses PyQtGraph's normal event path.
        self.mouse_proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=30, slot=self._hover)
        layout.addWidget(self.plot, 1)
        self.readout = QTreeWidget()
        self.readout.setHeaderLabels(("Signal / visibility", "Sample time [s]", "Recorded value", "Data status", ""))
        self.readout.setRootIsDecorated(False)
        self.readout.setUniformRowHeights(True)
        self.readout.setMinimumHeight(80)
        self.readout.setMaximumHeight(125)
        self.readout.setColumnWidth(0, 245)
        self.readout.setColumnWidth(1, 130)
        self.readout.setColumnWidth(2, 150)
        self.readout.setColumnWidth(3, 180)
        self.readout.itemChanged.connect(self._visibility_changed)
        layout.addWidget(self.readout)
        self.hint = QLabel("Add signals from the browser. Wheel: zoom • left drag: pan • drag an axis: scale that axis")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def set_selected(self, active: bool):
        self.setProperty("active", active)
        self.select_button.setText("Selected" if active else "Select")
        self.style().unpolish(self)
        self.style().polish(self)

    def add_signal(self, data: ChannelData):
        key = data.info.key
        if key in self.traces:
            return
        color = trace_color(self._color_index)
        self._color_index += 1
        curve = self.plot.plot(
            data.timestamps, data.samples, pen=pg.mkPen(color, width=1.3),
            name=escape(data.info.label), connect="finite",
        )
        curve.setClipToView(True)
        # Peak envelopes retain short spikes when many samples share a pixel.
        # Skip downsampling with gaps: averaging/envelopes could conceal invalidity.
        curve.setDownsampling(auto=not data.invalid_count, method="peak")
        status = "Empty channel" if not len(data.samples) else f"{len(data.samples):,} samples"
        if data.invalid_count:
            status += f"; {data.invalid_count:,} invalid/missing"
        if data.notes:
            status += "; " + "; ".join(data.notes)
        row = QTreeWidgetItem((data.info.label, "—", "—", status, ""))
        row.setData(0, Qt.ItemDataRole.UserRole, key)
        row.setForeground(0, color)
        row.setCheckState(0, Qt.CheckState.Checked)
        row.setToolTip(0, data.info.description)
        row.setToolTip(3, status)
        self.readout.addTopLevelItem(row)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self.remove_signal(key))
        self.readout.setItemWidget(row, 4, remove)
        self.traces[key] = Trace(data, curve, row)
        self._update_units()
        if len(self.traces) == 1:
            self.fit_all()
        self.traces_changed.emit()

    def remove_signal(self, key: ChannelKey):
        trace = self.traces.pop(key, None)
        if trace is None:
            return
        self.plot.removeItem(trace.curve)
        self.readout.takeTopLevelItem(self.readout.indexOfTopLevelItem(trace.row))
        self._update_units()
        self.traces_changed.emit()

    def _visibility_changed(self, row, column):
        key = row.data(0, Qt.ItemDataRole.UserRole)
        if column == 0 and key in self.traces:
            trace = self.traces[key]
            trace.curve.setVisible(row.checkState(0) == Qt.CheckState.Checked)
            if not trace.curve.isVisible():
                row.setText(1, "—")
                row.setText(2, "Hidden")
            self._update_units()
            self.traces_changed.emit()

    def visible_traces(self):
        return [trace for trace in self.traces.values() if trace.curve.isVisible()]

    def _update_units(self):
        units = sorted({trace.data.info.unit for trace in self.visible_traces() if trace.data.info.unit})
        self.plot.setLabel("left", " / ".join(units) if units else "Value")

    def time_bounds(self):
        arrays = [trace.data.timestamps for trace in self.visible_traces() if len(trace.data.timestamps)]
        return (min(t[0] for t in arrays), max(t[-1] for t in arrays)) if arrays else None

    def fit_all(self):
        bounds = self.time_bounds()
        if bounds:
            low, high = bounds
            self.plot.setXRange(low, high if high > low else low + 1e-6, padding=0.02)
        self.fit_y_visible()

    def fit_y_visible(self):
        low, high = self.plot.viewRange()[0]
        extrema = []
        for trace in self.visible_traces():
            data = trace.data
            start = np.searchsorted(data.timestamps, low, side="left")
            stop = np.searchsorted(data.timestamps, high, side="right")
            values = data.samples[start:stop]
            values = values[np.isfinite(values)]
            if len(values):
                extrema.extend((float(values.min()), float(values.max())))
        if extrema:
            was_auto = self.auto_y.isChecked()
            minimum, maximum = min(extrema), max(extrema)
            if minimum == maximum:
                margin = max(abs(minimum) * 0.01, 1e-9)
                minimum, maximum = minimum - margin, maximum + margin
            self.plot.setYRange(minimum, maximum, padding=0.08)
            if was_auto:
                self.plot.enableAutoRange(axis="y", enable=True)
                self.plot.getViewBox().setAutoVisible(y=True)

    def _auto_y_changed(self, enabled):
        self.plot.enableAutoRange(axis="y", enable=enabled)
        self.plot.getViewBox().setAutoVisible(y=enabled)

    def _manual_range(self, axes):
        if axes[1]:
            self.auto_y.setChecked(False)

    def inspect_at(self, time: float):
        self.cursor.setPos(time)
        self.cursor.show()
        for trace in self.visible_traces():
            sample = trace.data.nearest(time)
            if sample is None:
                trace.row.setText(1, "—")
                trace.row.setText(2, "No samples")
            else:
                timestamp, value = sample
                trace.row.setText(1, f"{timestamp:.9g}")
                text = f"{value:.9g} {trace.data.info.unit}".strip() if np.isfinite(value) else "Invalid / missing"
                trace.row.setText(2, text)
        self.hint.setText(f"Cursor: {time:.9g} s • readout uses each signal's nearest recorded sample; no interpolation")

    def _hover(self, event):
        point = event[0]
        if self.plot.getViewBox().sceneBoundingRect().contains(point):
            self.inspect_at(self.plot.getViewBox().mapSceneToView(point).x())

    def dispose(self):
        self.mouse_proxy.disconnect()
        for key in list(self.traces):
            self.remove_signal(key)
        self.plot.close()
