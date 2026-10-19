import argparse
import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from .window import MainWindow


STYLE = """
QMainWindow, QWidget { background: #18232f; color: #e0e7ee; font-family: 'Segoe UI'; font-size: 10pt; }
QToolBar { spacing: 12px; padding: 10px; border-bottom: 1px solid #36485b; }
QPushButton, QToolButton { background: #2d4154; border: 1px solid #466078; border-radius: 4px; padding: 5px 10px; }
QPushButton:hover, QToolButton:hover { background: #3c5870; }
QPushButton:disabled { color: #8394a3; }
QLineEdit { background: #101923; border: 1px solid #46576a; border-radius: 3px; padding: 5px; }
QTableView, QTreeWidget { background: #111c27; alternate-background-color: #1c2b39; gridline-color: #2b3e50; }
QHeaderView::section { background: #293b4c; color: #e0e7ee; padding: 5px; border: 0; }
QTableView::item:selected, QTreeWidget::item:selected { background: #315d7c; }
QFrame#waveformPanel { border: 1px solid #3b4e61; border-radius: 5px; }
QFrame#waveformPanel[active="true"] { border: 2px solid #55c9ff; }
QLabel#sectionHeading { color: #55c9ff; font-weight: bold; }
QSplitter::handle { background: #304454; }
QStatusBar { border-top: 1px solid #36485b; }
QToolTip { background: #263b4c; color: #ffffff; border: 1px solid #6c91ab; }
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive MDF waveform viewer")
    parser.add_argument("recording", nargs="?", help="Optional MDF recording to open")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("MDF Waveform Viewer")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    pg.setConfigOptions(antialias=False, foreground="#c9d8e5")
    window = MainWindow()
    window.show()
    if args.recording:
        window.open_file(args.recording)
    return app.exec()
