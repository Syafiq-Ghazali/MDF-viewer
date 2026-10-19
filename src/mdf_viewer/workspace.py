"""Panel ordering, selection, resizing, and guarded time-axis synchronization."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QSplitter, QVBoxLayout, QWidget

from .panel import WaveformPanel


class WaveformWorkspace(QWidget):
    selection_changed = Signal(object)
    traces_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.panels: list[WaveformPanel] = []
        self.active: WaveformPanel | None = None
        self.synchronized = True
        self._syncing = False
        self._next_number = 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.scroll.setWidget(self.splitter)
        layout.addWidget(self.scroll)
        self.add_panel()

    def add_panel(self):
        panel = WaveformPanel(f"Waveform {self._next_number}")
        self._next_number += 1
        self.panels.append(panel)
        self.splitter.addWidget(panel)
        panel.selected.connect(self.select)
        panel.remove_requested.connect(self.remove_panel)
        panel.move_requested.connect(self.move_panel)
        panel.traces_changed.connect(self.traces_changed)
        panel.renamed.connect(lambda: self.selection_changed.emit(self.active))
        panel.plot.getViewBox().sigXRangeChanged.connect(
            lambda _view, limits, source=panel: self._sync_from(source, limits)
        )
        if self.synchronized and self.active:
            panel.plot.setXRange(*self.active.plot.viewRange()[0], padding=0)
        self.select(panel)
        self._resize_content()
        self.scroll.ensureWidgetVisible(panel)
        return panel

    def select(self, panel):
        if panel not in self.panels:
            return
        self.active = panel
        for item in self.panels:
            item.set_selected(item is panel)
        self.selection_changed.emit(panel)

    def remove_panel(self, panel):
        if panel not in self.panels:
            return
        self.panels.remove(panel)
        panel.dispose()
        panel.setParent(None)
        panel.deleteLater()
        if self.active is panel:
            self.active = None
            if self.panels:
                self.select(self.panels[-1])
            else:
                self.selection_changed.emit(None)
        self._resize_content()
        self.traces_changed.emit()

    def move_panel(self, panel, offset):
        index = self.panels.index(panel)
        target = index + offset
        if not 0 <= target < len(self.panels):
            return
        sizes = dict(zip(self.panels, self.splitter.sizes()))
        self.panels.pop(index)
        self.panels.insert(target, panel)
        self.splitter.insertWidget(target, panel)
        self.splitter.setSizes([sizes[item] for item in self.panels])
        self.select(panel)

    def _resize_content(self):
        self.splitter.setMinimumHeight(sum(panel.minimumHeight() for panel in self.panels) + max(0, len(self.panels) - 1) * 8)

    def set_synchronized(self, enabled):
        self.synchronized = enabled
        if enabled and self.active:
            self._sync_from(self.active, self.active.plot.viewRange()[0])

    def _sync_from(self, source, limits):
        if not self.synchronized or self._syncing or source not in self.panels:
            return
        self._syncing = True
        try:
            for panel in self.panels:
                if panel is not source:
                    panel.plot.setXRange(*limits, padding=0)
        finally:
            self._syncing = False

    def fit_all(self):
        if self.synchronized:
            bounds = [panel.time_bounds() for panel in self.panels]
            bounds = [bound for bound in bounds if bound is not None]
            if bounds and self.panels:
                low, high = min(b[0] for b in bounds), max(b[1] for b in bounds)
                self.panels[0].plot.setXRange(low, high if high > low else low + 1e-6, padding=0.02)
            for panel in self.panels:
                panel.fit_y_visible()
        else:
            for panel in self.panels:
                panel.fit_all()

    def reset(self):
        for panel in list(self.panels):
            self.remove_panel(panel)
        self._next_number = 1
        self.add_panel()
