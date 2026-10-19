"""Searchable metadata table; no channel samples are loaded here."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)

from .data import ChannelInfo, ChannelKey


class ChannelModel(QAbstractTableModel):
    headers = ("Signal", "Unit", "Identity", "Displayed", "Samples", "Description")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.channels: list[ChannelInfo] = []
        self.usage: dict[ChannelKey, tuple[int, int]] = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.channels)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        channel = self.channels[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{channel.label}\n{channel.description}\n{channel.sample_count:,} recorded samples"
        if role == Qt.ItemDataRole.DisplayRole:
            assigned, visible = self.usage.get(channel.key, (0, 0))
            usage = f"{assigned} panels / {visible} shown" if assigned else ""
            return (
                channel.name, channel.unit, f"G{channel.key.group}:C{channel.key.index}",
                usage, str(channel.sample_count), channel.description,
            )[index.column()]
        return None

    def set_channels(self, channels: list[ChannelInfo]):
        self.beginResetModel()
        self.channels = channels
        self.usage = {}
        self.endResetModel()

    def set_usage(self, usage: dict[ChannelKey, tuple[int, int]]):
        self.usage = usage
        if self.channels:
            self.dataChanged.emit(self.index(0, 3), self.index(len(self.channels) - 1, 3))


class SignalBrowser(QWidget):
    add_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel("SIGNAL BROWSER")
        heading.setObjectName("sectionHeading")
        self.summary = QLabel("Open an MDF recording to discover its channels.")
        self.summary.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search names, units, or descriptions…")
        self.search.setClearButtonEnabled(True)
        self.model = ChannelModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 55)
        self.table.setColumnWidth(2, 85)
        self.target = QLabel("Target: Waveform 1")
        self.target.setWordWrap(True)
        self.add_button = QPushButton("Add selected signals to panel")
        self.add_button.setEnabled(False)
        hint = QLabel("Select a panel, then double-click a signal or select several with Ctrl / Shift and click Add.")
        hint.setWordWrap(True)
        for widget in (heading, self.summary, self.search, self.table, self.target, self.add_button, hint):
            layout.addWidget(widget)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.add_button.clicked.connect(self.add_selection)
        self.table.doubleClicked.connect(self.add_selection)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)

    def _selection_changed(self, *_):
        self.add_button.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def add_selection(self, *_):
        keys = [
            self.model.channels[self.proxy.mapToSource(index).row()].key
            for index in self.table.selectionModel().selectedRows()
        ]
        if keys:
            self.add_requested.emit(keys)

    def set_channels(self, channels):
        self.search.clear()
        self.model.set_channels(channels)
        self.summary.setText(f"{len(channels):,} measurement channels • samples load when added")
        self.add_button.setEnabled(False)
