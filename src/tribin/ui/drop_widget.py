"""Widget flottant de dépôt : toujours au premier plan, déplaçable, quatre états.

Au repos (« Trier ») · fichiers au-dessus (« Dépose pour trier ») · analyse en cours · prêt à valider.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tribin.ui.components import Pill
from tribin.ui.icons import logo_pixmap
from tribin.ui.theme import NAVY

STYLE = f"""
QFrame#Idle, QFrame#Busy, QFrame#Ready {{ background: {NAVY}; border: none; border-radius: 16px; }}
QFrame#Idle QLabel, QFrame#Busy QLabel, QFrame#Ready QLabel {{ color: white; background: transparent; }}
QFrame#Hover {{ background: white; border: 3px dashed #14B8A6; border-radius: 20px; }}
QFrame#Hover QLabel {{ background: transparent; }}
QLabel#WTitle {{ font-weight: 700; font-size: 14px; }}
QLabel#WSub {{ color: #C9CDE6; font-size: 12px; }}
QPushButton#WAuto {{ background: #14B8A6; color: {NAVY}; border: none; border-radius: 8px; padding: 8px 12px; font-weight: 700; }}
QPushButton#WAuto:hover {{ background: #2DD4BF; }}
QPushButton#WOpen {{ background: transparent; color: white; border: 1px solid #4A5280; border-radius: 8px; padding: 7px 12px; font-weight: 600; }}
QPushButton#WOpen:hover {{ background: #2C3460; }}
QProgressBar {{ background: #3A4270; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: #14B8A6; border-radius: 3px; }}
"""


def dropped_paths(event: QDropEvent) -> list[Path]:
    return [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]


class DropWidget(QWidget):
    files_dropped = Signal(list)
    clicked = Signal()
    auto_clicked = Signal()  # « Ranger les N prêts » : sans ouvrir la fenêtre

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self.setToolTip("Glissez vos fichiers ici pour les trier.\nClic : ouvrir TriBin · glisser : déplacer")
        self.counts = {"total": 0, "analyzing": 0, "ready": 0, "check": 0}
        self._hovering = False
        self._drag_from: QPoint | None = None
        self._moved = False

        self.stack = QStackedWidget()
        self.idle = self._card("Idle")
        row = QHBoxLayout(self.idle)
        row.setContentsMargins(8, 8, 16, 8)
        icon = QLabel()
        icon.setPixmap(logo_pixmap(40))
        label = QLabel("Trier")
        label.setObjectName("WTitle")
        row.addWidget(icon)
        row.addWidget(label)

        self.hover = self._card("Hover")
        self.hover.setFixedSize(180, 196)
        column = QVBoxLayout(self.hover)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big = QLabel()
        big.setPixmap(logo_pixmap(64))
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop = QLabel("Déposez pour trier")
        drop.setObjectName("WTitle")
        drop.setStyleSheet("color: #0F766E;")
        drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hover_count = QLabel()
        self.hover_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hover_count.setStyleSheet("color: #4B5070; font-size: 12px;")
        for widget in (big, drop, self.hover_count):
            column.addWidget(widget)

        self.busy = self._card("Busy")
        self.busy.setFixedWidth(200)
        column = QVBoxLayout(self.busy)
        column.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        title = QLabel("Analyse…")
        title.setObjectName("WTitle")
        self.busy_count = QLabel()
        self.busy_count.setObjectName("WSub")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.busy_count)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        hint = QLabel("Vous pouvez continuer à travailler.")
        hint.setObjectName("WSub")
        column.addLayout(top)
        column.addWidget(self.progress)
        column.addWidget(hint)

        self.ready_card = self._card("Ready")
        self.ready_card.setFixedWidth(230)
        column = QVBoxLayout(self.ready_card)
        column.setContentsMargins(14, 12, 14, 14)
        column.setSpacing(10)
        top = QHBoxLayout()
        self.ready_icon = QLabel()
        self.ready_title = QLabel()
        self.ready_title.setObjectName("WTitle")
        top.addWidget(self.ready_icon)
        top.addWidget(self.ready_title, 1)
        chips = QHBoxLayout()
        self.ready_pill = Pill("", ("#DDF5F1", "#0F766E"))
        self.check_pill = Pill("", ("#FDE4E2", "#A42A25"))
        chips.addWidget(self.ready_pill)
        chips.addWidget(self.check_pill)
        chips.addStretch()
        self.auto_button = QPushButton()
        self.auto_button.setObjectName("WAuto")
        self.auto_button.setToolTip("Range les fichiers prêts sans ouvrir la fenêtre. Un fichier qui demanderait "
                                    "un nouveau dossier attend votre avis. Tout s'annule depuis l'Historique.")
        self.auto_button.clicked.connect(self.auto_clicked)
        self.open_button = QPushButton("Ouvrir TriBin")
        self.open_button.setObjectName("WOpen")
        self.open_button.clicked.connect(self.clicked)
        column.addLayout(top)
        column.addLayout(chips)
        column.addWidget(self.auto_button)
        column.addWidget(self.open_button)

        for card in (self.idle, self.hover, self.busy, self.ready_card):
            self.stack.addWidget(card)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)
        self._update()

    @staticmethod
    def _card(name: str) -> QFrame:
        card = QFrame()
        card.setObjectName(name)
        return card

    # --- état ---------------------------------------------------------------------------------

    def set_state(self, total: int, analyzing: int = 0, ready: int = 0, check: int = 0) -> None:
        self.counts = {"total": total, "analyzing": analyzing, "ready": ready, "check": check}
        self._update()

    def set_count(self, count: int) -> None:
        self.set_state(total=count, ready=count)

    def _update(self) -> None:
        c = self.counts
        if self._hovering:
            card = self.hover
        elif c["analyzing"]:
            done = c["total"] - c["analyzing"]
            self.busy_count.setText(f"{done} / {c['total']}")
            self.progress.setRange(0, max(1, c["total"]))
            self.progress.setValue(done)
            card = self.busy
        elif c["total"]:
            self.ready_icon.setPixmap(logo_pixmap(40, c["total"]))
            self.ready_title.setText(f"{c['total']} à valider")
            self.ready_pill.setText(f"{c['ready']} prêt{'s' if c['ready'] > 1 else ''}")
            self.ready_pill.setVisible(bool(c["ready"]))
            self.check_pill.setText(f"{c['check']} à vérifier")
            self.check_pill.setVisible(bool(c["check"]))
            self.auto_button.setText(f"Ranger les {c['ready']} prêts" if c["ready"] > 1 else "Ranger le fichier prêt")
            self.auto_button.setVisible(bool(c["ready"]))
            card = self.ready_card
        else:
            card = self.idle
        self.stack.setCurrentWidget(card)
        self.stack.setFixedSize(card.sizeHint().expandedTo(card.minimumSize()))
        self.adjustSize()
        self.keep_on_screen()

    def keep_on_screen(self) -> None:
        """La carte change de taille selon l'état : elle ne doit jamais dépasser du bord de l'écran."""
        screen = self.screen()
        if screen is None or not self.isVisible():
            return
        area = screen.availableGeometry()
        x = max(area.left() + 8, min(self.x(), area.right() - self.width() - 8))
        y = max(area.top() + 8, min(self.y(), area.bottom() - self.height() - 8))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # --- glisser-déposer ----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            n = len(event.mimeData().urls())
            self.hover_count.setText(f"{n} fichier{'s' if n > 1 else ''}")
            self._hovering = True
            self._update()

    def dragLeaveEvent(self, event) -> None:
        self._hovering = False
        self._update()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hovering = False
        self._update()
        paths = dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)

    # --- déplacement à la souris ----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            self._moved = True

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_from is not None and not self._moved:
            self.clicked.emit()
        self._drag_from = None
