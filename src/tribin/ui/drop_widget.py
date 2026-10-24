"""Widget flottant : petite zone de dépôt toujours au premier plan, déplaçable."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tribin.ui.icons import logo_pixmap


def dropped_paths(event: QDropEvent) -> list[Path]:
    return [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]


class DropWidget(QWidget):
    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setToolTip("Glisse tes fichiers ici pour les ranger.\nClic : ouvrir la corbeille · glisser : déplacer")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon)
        self.label = QLabel("TriBin")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color: white; background: #1F2544; border-radius: 9px; padding: 2px 9px; font-weight: 600;")
        layout.addWidget(self.label)
        self._drag_from: QPoint | None = None
        self._moved = False
        self.set_count(0)
        self.resize(96, 110)

    def set_count(self, count: int, highlight: bool = False) -> None:
        self.icon.setPixmap(logo_pixmap(72, count))
        self.label.setText("Dépose ici" if highlight else (f"{count} en attente" if count else "TriBin"))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.label.setText("Dépose ici")

    def dragLeaveEvent(self, event) -> None:
        self.label.setText("TriBin")

    def dropEvent(self, event: QDropEvent) -> None:
        paths = dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            self._moved = True

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._moved:
            self.clicked.emit()
        self._drag_from = None
