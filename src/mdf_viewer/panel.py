"""One interactive plot, with per-signal visibility and recorded-sample readout."""

from dataclasses import dataclass
from html import escape

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from .data import ChannelData, ChannelKey
from .drag import channel_keys


@dataclass
class Trace:
    data: ChannelData
    curve: pg.PlotDataItem
    row: QTreeWidgetItem
    view: pg.ViewBox | None = None


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
    channels_dropped = Signal(object, object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("waveformPanel")
        self.setAcceptDrops(True)
        self.setMinimumHeight(360)
        self.traces: dict[ChannelKey, Trace] = {}
        self._extra_views: list[tuple[pg.ViewBox, pg.AxisItem]] = []
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
        self.separate_y = QCheckBox("Separate Y scales")
        self.separate_y.setChecked(True)
        self.separate_y.setToolTip("Give each signal its own colored Y axis so different ranges stay visible.")
        tools.addWidget(self.separate_y)
        tools.addStretch()
        layout.addLayout(tools)
        self.plot = pg.PlotWidget(background="#101923")
        # Handle channel drops before the graphics scene, including over curves
        # and legends, without interfering with normal plot pan/zoom events.
        self.plot.viewport().setAcceptDrops(True)
        self.plot.viewport().installEventFilter(self)
        self.plot.setMinimumHeight(140)
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.setLabel("left", "Value")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.addLegend(offset=(12, 8))
        self.plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.plot.getViewBox().sigRangeChangedManually.connect(self._manual_range)
        self.plot.getViewBox().sigResized.connect(self._update_views)
        self.plot.enableAutoRange(axis="x", enable=False)
        self.plot.scene().sigMouseClicked.connect(lambda *_: self.selected.emit(self))
        self.cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#8c9dae", style=Qt.PenStyle.DashLine))
        self.plot.addItem(self.cursor, ignoreBounds=True)
        self.cursor.hide()
        # Rate-limit readouts; curve navigation uses PyQtGraph's normal event path.
        self.mouse_proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=30, slot=self._hover)
        self.plot_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.addWidget(self.plot)
        self.readout = QTreeWidget()
        self.readout.setHeaderLabels(("Signals on this waveform", "Sample time [s]", "Recorded value", "Data status", ""))
        self.readout.setRootIsDecorated(False)
        self.readout.setMinimumWidth(240)
        self.readout.setWordWrap(True)
        self.readout.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Keep the original readout fields as item data; display them together
        # beneath the signal name so Remove is always visible without scrolling.
        for column in (1, 2, 3):
            self.readout.hideColumn(column)
        self.readout.header().setStretchLastSection(False)
        self.readout.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.readout.header().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.readout.itemChanged.connect(self._visibility_changed)
        self.plot_splitter.addWidget(self.readout)
        self.plot_splitter.setSizes([700, 300])
        self.plot_splitter.setStretchFactor(0, 1)
        self.plot_splitter.setStretchFactor(1, 0)
        layout.addWidget(self.plot_splitter, 1)
        self.separate_y.toggled.connect(self._rebuild_views)
        self.hint = QLabel("Drag signals here from the browser. Wheel: zoom • left drag: pan • drag an axis: scale that axis")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def eventFilter(self, watched, event):
        if watched is self.plot.viewport():
            handlers = {
                QEvent.Type.DragEnter: self.dragEnterEvent,
                QEvent.Type.DragMove: self.dragMoveEvent,
                QEvent.Type.Drop: self.dropEvent,
            }
            handler = handlers.get(event.type())
            if handler:
                handler(event)
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if channel_keys(event.mimeData()) and event.possibleActions() & Qt.DropAction.CopyAction:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        self.dragEnterEvent(event)
        if event.isAccepted():
            self.channels_dropped.emit(self, event.mimeData())

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
        curve = pg.PlotDataItem(
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
        row.setToolTip(0, f"{data.info.label}\n{data.info.description}\n{status}")
        row.setToolTip(3, status)
        self.readout.addTopLevelItem(row)
        remove = QPushButton("×")
        remove.setFixedWidth(30)
        remove.setToolTip(f"Remove {data.info.label}")
        remove.setAccessibleName(f"Remove {data.info.label}")
        remove.clicked.connect(lambda: self.remove_signal(key))
        self.readout.setItemWidget(row, 4, remove)
        self.traces[key] = Trace(data, curve, row)
        self.plot.plotItem.legend.addItem(curve, escape(data.info.label))
        self._update_row(self.traces[key])
        self._rebuild_views()
        if len(self.traces) == 1:
            self.fit_all()
        self.traces_changed.emit()

    def remove_signal(self, key: ChannelKey):
        trace = self.traces.pop(key, None)
        if trace is None:
            return
        trace.view.removeItem(trace.curve)
        self.plot.plotItem.legend.removeItem(trace.curve)
        self.readout.takeTopLevelItem(self.readout.indexOfTopLevelItem(trace.row))
        self._rebuild_views()
        self.traces_changed.emit()

    def _visibility_changed(self, row, column):
        key = row.data(0, Qt.ItemDataRole.UserRole)
        if column == 0 and key in self.traces:
            trace = self.traces[key]
            visible = row.checkState(0) == Qt.CheckState.Checked
            if trace.curve.isVisible() == visible:
                return
            trace.curve.setVisible(visible)
            if not trace.curve.isVisible():
                row.setText(1, "—")
                row.setText(2, "Hidden")
            self._update_row(trace)
            self._rebuild_views()
            self.traces_changed.emit()

    def visible_traces(self):
        return [trace for trace in self.traces.values() if trace.curve.isVisible()]

    def _update_row(self, trace):
        row = trace.row
        value = row.text(2)
        sample = row.text(1)
        detail = value if sample == "—" else f"{value} · {sample} s"
        row.setText(0, f"{trace.data.info.label}\n{detail}")

    def _update_views(self, *_):
        primary = self.plot.getViewBox()
        for view, _axis in self._extra_views:
            view.setGeometry(primary.sceneBoundingRect())
            view.linkedViewChanged(primary, pg.ViewBox.XAxis)

    def _rebuild_views(self, *_):
        primary = self.plot.getViewBox()
        for trace in self.traces.values():
            if trace.view is not None:
                trace.view.removeItem(trace.curve)
        old_views, self._extra_views = self._extra_views, []
        for view, axis in old_views:
            axis.unlinkFromView()
            self.plot.plotItem.layout.removeItem(axis)
            self.plot.scene().removeItem(axis)
            axis.deleteLater()
            view.setXLink(None)
            view.close()
            self.plot.scene().removeItem(view)
            view.deleteLater()
        visible = self.visible_traces()
        left = self.plot.getAxis("left")
        if self.separate_y.isChecked() and visible:
            first = visible[0]
            color = first.curve.opts["pen"].color()
            left.setLabel(first.data.info.name, units=first.data.info.unit, color=color.name())
            left.setPen(color)
            left.setTextPen(color)
        else:
            units = sorted({trace.data.info.unit for trace in visible if trace.data.info.unit})
            left.setLabel(" / ".join(units) if units else "Value")
            left.setPen(pg.getConfigOption("foreground"))
            left.setTextPen(pg.getConfigOption("foreground"))
        for trace in self.traces.values():
            view = primary
            if self.separate_y.isChecked() and trace.curve.isVisible() and trace is not visible[0]:
                view = pg.ViewBox(enableMenu=False)
                # The primary view receives plot gestures. Each colored axis can
                # still scale its own view; all views share recorded time.
                view.setZValue(-10)
                view.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                view.setAcceptHoverEvents(False)
                self.plot.scene().addItem(view)
                view.setXLink(primary)
                view.sigRangeChangedManually.connect(self._manual_range)
                axis = pg.AxisItem("right")
                color = trace.curve.opts["pen"].color()
                axis.setLabel(trace.data.info.name, units=trace.data.info.unit, color=color.name())
                axis.setPen(color)
                axis.setTextPen(color)
                self.plot.plotItem.layout.addItem(axis, 2, 3 + len(self._extra_views))
                axis.linkToView(view)
                self._extra_views.append((view, axis))
            trace.view = view
            # Parent first: clipped/downsampled curves need a ViewBox during
            # their scene-change callback, including when switching Y scales.
            trace.curve.setParentItem(view.childGroup)
            view.addItem(trace.curve)
        self._update_views()
        self.fit_y_visible()

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
        extrema = {}
        for trace in self.visible_traces():
            data = trace.data
            start = np.searchsorted(data.timestamps, low, side="left")
            stop = np.searchsorted(data.timestamps, high, side="right")
            values = data.samples[start:stop]
            values = values[np.isfinite(values)]
            if len(values):
                extrema.setdefault(trace.view, []).extend((float(values.min()), float(values.max())))
        for view, values in extrema.items():
            minimum, maximum = min(values), max(values)
            if minimum == maximum:
                margin = max(abs(minimum) * 0.01, 1e-9)
                minimum, maximum = minimum - margin, maximum + margin
            view.setYRange(minimum, maximum, padding=0.08)
        self._auto_y_changed(self.auto_y.isChecked())

    def _auto_y_changed(self, enabled):
        for view in [self.plot.getViewBox(), *(view for view, _axis in self._extra_views)]:
            view.enableAutoRange(axis="y", enable=enabled)
            view.setAutoVisible(y=enabled)

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
            self._update_row(trace)
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
