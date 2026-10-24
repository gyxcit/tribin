"""File des fichiers en attente : recherche, groupes « À vérifier » / « Prêts à ranger », « Tout valider »."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tribin.service.queue import QueueItem
from tribin.ui.components import KeyButton, Pill, elided, item_level, short_confidence, thumbnail

GROUPS = (("wait", "Analyse en cours", "GroupWait"), ("check", "À vérifier", "GroupReview"),
          ("ready", "Prêts à ranger", "GroupReady"))


def group_of(item: QueueItem) -> str:
    key = item_level(item)[0]
    return "wait" if key == "wait" else "check" if key == "check" else "ready"


class QueueRow(QFrame):
    """Ligne : aperçu, nom d'origine, destination proposée, pastille de confiance."""

    def __init__(self, item: QueueItem):
        super().__init__()
        self.setObjectName("QueueRow")
        self.file_id = item.file_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)
        thumb = QLabel()
        thumb.setFixedSize(40, 48)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setPixmap(thumbnail(Path(item.staged_path), 40, 48))
        layout.addWidget(thumb)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        original = Path(item.original_path).name
        name = QLabel()
        name.setStyleSheet("font-weight: 600;")
        name.setText(elided(original, name, 190))
        name.setToolTip(original)
        p = item.proposal
        parts = [x for x in (p.target_folder if p else "").split("/") if x]
        where = QLabel()
        where.setObjectName("Muted")
        short = " › ".join([parts[-2].split("_")[0], parts[-1]] if len(parts) >= 2 else parts)
        where.setText(elided(f"→ {short}", where, 190) if short else "")
        texts.addWidget(name)
        texts.addWidget(where)
        layout.addLayout(texts, 1)
        _, _, background, text = item_level(item)
        layout.addWidget(Pill(short_confidence(item), (background, text)), 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class QueuePanel(QWidget):
    selection_changed = Signal(str)
    validate_all_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.items: list[QueueItem] = []
        self.order: list[str] = []  # file_id dans l'ordre d'affichage
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Rechercher un fichier…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._rebuild(self.current_file_id()))
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("Queue")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSpacing(1)
        self.list.currentRowChanged.connect(self._row_changed)
        layout.addWidget(self.list, 1)
        self.validate_all = KeyButton("Tout valider", "", "Primary")
        self.validate_all.clicked.connect(self.validate_all_clicked)
        layout.addWidget(self.validate_all)
        note = QLabel("Une simulation te montre tout avant le moindre déplacement.")
        note.setObjectName("Muted")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(note)

    # --- contenu ------------------------------------------------------------------------------

    def set_items(self, items: list[QueueItem], current_id: str | None) -> None:
        self.items = items
        ready = sum(1 for i in items if group_of(i) == "ready")
        self.validate_all.label.setText(f"Tout valider ({ready} prêt{'s' if ready > 1 else ''})")
        self.validate_all.setEnabled(ready > 0)
        self._rebuild(current_id)

    def _rebuild(self, current_id: str | None) -> None:
        needle = self.search.text().strip().casefold()
        visible = [i for i in self.items if not needle or needle in Path(i.original_path).name.casefold()
                   or needle in (i.proposal.new_name.casefold() if i.proposal else "")]
        self.list.blockSignals(True)
        self.list.clear()
        self.order = []
        for key, title, style in GROUPS:
            members = [i for i in visible if group_of(i) == key]
            if not members:
                continue
            header = QListWidgetItem()
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            label = QWidget()
            row = QHBoxLayout(label)
            row.setContentsMargins(4, 10, 4, 2)
            caption = QLabel(title.upper())
            caption.setObjectName(style)
            count = QLabel(str(len(members)))
            count.setObjectName("Muted")
            row.addWidget(caption)
            row.addStretch()
            row.addWidget(count)
            header.setSizeHint(label.sizeHint())
            self.list.addItem(header)
            self.list.setItemWidget(header, label)
            for item in members:
                widget = QueueRow(item)
                entry = QListWidgetItem()
                entry.setData(Qt.ItemDataRole.UserRole, item.file_id)
                entry.setSizeHint(widget.sizeHint())
                self.list.addItem(entry)
                self.list.setItemWidget(entry, widget)
                self.order.append(item.file_id)
        self.list.blockSignals(False)
        target = current_id if current_id in self.order else (self.order[0] if self.order else None)
        if target:
            self.select_file(target)
        else:
            self.selection_changed.emit("")

    # --- sélection ----------------------------------------------------------------------------

    def _row_of(self, file_id: str) -> int:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == file_id:
                return row
        return -1

    def select_file(self, file_id: str) -> None:
        row = self._row_of(file_id)
        if row >= 0:
            if self.list.currentRow() == row:
                self._row_changed(row)
            else:
                self.list.setCurrentRow(row)

    def current_file_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select_next(self) -> None:
        current = self.current_file_id()
        if current in self.order and self.order.index(current) + 1 < len(self.order):
            self.select_file(self.order[self.order.index(current) + 1])

    def _row_changed(self, row: int) -> None:
        for index in range(self.list.count()):
            widget = self.list.itemWidget(self.list.item(index))
            if isinstance(widget, QueueRow):
                widget.set_selected(index == row)
        entry = self.list.item(row) if row >= 0 else None
        self.selection_changed.emit(entry.data(Qt.ItemDataRole.UserRole) if entry else "")
