"""Internal channel drags retain identities only while their recording is open."""

from PySide6.QtCore import QMimeData, QPersistentModelIndex


class ChannelMimeData(QMimeData):
    mime_type = "application/x-mdf-viewer-channels"

    def __init__(self, model, rows):
        super().__init__()
        self.source_model = model
        self.indexes = [QPersistentModelIndex(model.index(row, 0)) for row in rows]
        self.setData(self.mime_type, b"channels")

    def keys(self):
        # Model resets invalidate persistent indexes, preventing a drag started
        # in an old recording from adding unrelated channels after a file switch.
        if not self.indexes or not all(index.isValid() for index in self.indexes):
            return []
        if not self.source_model.parent().isEnabled():
            return []
        return [self.source_model.channels[index.row()].key for index in self.indexes]


def channel_keys(mime):
    return mime.keys() if isinstance(mime, ChannelMimeData) else []
