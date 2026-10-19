"""All parser access is serialized on one Qt worker thread."""

from PySide6.QtCore import QObject, Signal, Slot

from .data import MDFDataManager


class FileWorker(QObject):
    opened = Signal(int, str, object)
    loaded = Signal(int, object, object)
    failed = Signal(int, str, object, str)

    def __init__(self):
        super().__init__()
        self.manager = MDFDataManager()
        self.session = 0

    @Slot(int, str)
    def open(self, session: int, path: str) -> None:
        try:
            channels = self.manager.open(path)
            self.session = session
            self.opened.emit(session, path, channels)
        except Exception as error:
            self.failed.emit(session, "open", None, str(error))

    @Slot(int, object)
    def load(self, session: int, key) -> None:
        if session != self.session:
            return
        try:
            self.loaded.emit(session, key, self.manager.load(key))
        except Exception as error:
            self.failed.emit(session, "load", key, str(error))

    @Slot()
    def close(self) -> None:
        self.manager.close()
