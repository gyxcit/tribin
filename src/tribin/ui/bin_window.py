"""Fenêtre Corbeille : file des fichiers en attente (à gauche) et proposition du fichier sélectionné (à droite)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tribin.config import is_within
from tribin.convention.naming import is_valid_name
from tribin.engine.proposer import normalize_rel
from tribin.service.bin import Validation
from tribin.service.queue import QueueItem
from tribin.ui.bin_detail import DetailPanel, elided, item_pill, short_confidence, thumbnail
from tribin.ui.drop_widget import dropped_paths
from tribin.ui.icons import app_icon, logo_pixmap
from tribin.ui.theme import pill_style

if TYPE_CHECKING:
    from tribin.ui.app import AppController


class QueueRow(QFrame):
    """Ligne de la file : vignette, nom d'origine, destination proposée, pastille de confiance."""

    def __init__(self, item: QueueItem):
        super().__init__()
        self.setObjectName("QueueRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        thumb = QLabel()
        thumb.setFixedSize(40, 40)
        thumb.setPixmap(thumbnail(Path(item.staged_path), 40))
        layout.addWidget(thumb)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel()
        name.setStyleSheet("font-weight: 600; background: transparent;")
        name.setText(elided(Path(item.original_path).name, name, 200))
        name.setToolTip(Path(item.original_path).name)
        target = item.proposal.target_folder if item.proposal and item.proposal.target_folder else ""
        where = QLabel()
        where.setObjectName("Muted")
        where.setStyleSheet("background: transparent;")
        where.setText(elided("→ " + "/".join(target.split("/")[-2:]), where, 200) if target else "")
        texts.addWidget(name)
        texts.addWidget(where)
        layout.addLayout(texts, 1)
        pill = QLabel(short_confidence(item))
        pill.setStyleSheet(pill_style(item_pill(item)))
        layout.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class BinWindow(QMainWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.items: list[QueueItem] = []
        self._edits: dict[str, dict] = {}  # file_id -> {"name", "folder", "alt"} modifiés par l'utilisateur
        self.setWindowTitle("TriBin — Corbeille")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(1120, 640)

        header = QFrame()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 12, 18, 12)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(34))
        hl.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Corbeille")
        title.setObjectName("HeaderTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("HeaderSubtitle")
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        hl.addLayout(titles)
        hl.addStretch()
        for label, slot in (("Historique", self.c.show_history), ("Réglages", self.c.show_settings)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            hl.addWidget(button)

        self.queue = QListWidget()
        self.queue.setObjectName("Queue")
        self.queue.setSpacing(2)
        self.queue.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue.currentRowChanged.connect(self._row_changed)
        self.validate_all_button = QPushButton("Tout valider")
        self.validate_all_button.setObjectName("Primary")
        self.validate_all_button.clicked.connect(self.validate_all)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.queue, 1)
        left.addWidget(self.validate_all_button)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setFixedWidth(380)

        self.detail = DetailPanel()
        self.detail.edited.connect(self._detail_edited)
        self.detail.alternative_chosen.connect(self._apply_alternative)
        self.detail.validate_clicked.connect(self.validate_selected)
        self.detail.return_clicked.connect(self.return_selected)
        self.detail.skip_clicked.connect(self.skip)
        self.detail.browse_clicked.connect(self.pick_folder)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(16, 16, 16, 16)
        bl.setSpacing(16)
        bl.addWidget(left_box)
        bl.addWidget(self.detail, 1)

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch()
        big_logo = QLabel()
        big_logo.setPixmap(logo_pixmap(112))
        big_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message = QLabel("Rien en attente.\nGlisse des fichiers ici ou sur le widget flottant : TriBin te propose où les ranger.")
        message.setObjectName("Empty")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(big_logo)
        el.addWidget(message)
        el.addStretch()

        self.pages = QStackedWidget()
        self.pages.addWidget(empty)
        self.pages.addWidget(body)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(header)
        cl.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.statusBar()

        for key, slot in [(Qt.Key.Key_Return, self.validate_selected), (Qt.Key.Key_Enter, self.validate_selected),
                          (Qt.Key.Key_E, self.edit_name), (Qt.Key.Key_A, self.choose_alternative),
                          (Qt.Key.Key_Escape, self.skip), (Qt.Key.Key_R, self.return_selected)]:
            shortcut = QShortcut(QKeySequence(key), self.queue)  # pas pendant la saisie d'un nom
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    # --- affichage ----------------------------------------------------------------------------

    def refresh(self, items: list[QueueItem]) -> None:
        current = self.current_item()
        current_id = current.file_id if current else None
        self.items = items
        self._edits = {k: v for k, v in self._edits.items() if any(i.file_id == k for i in items)}
        self.queue.blockSignals(True)
        self.queue.clear()
        for item in items:
            row = QueueRow(item)
            entry = QListWidgetItem()
            entry.setSizeHint(row.sizeHint())
            self.queue.addItem(entry)
            self.queue.setItemWidget(entry, row)
        self.queue.blockSignals(False)
        ready = sum(1 for i in items if i.status == "ready" and i.proposal)
        self.subtitle.setText(f"{len(items)} fichier(s) en attente · {ready} prêt(s)" if items else "Aucun fichier en attente")
        self.validate_all_button.setText(f"Tout valider ({ready})")
        self.validate_all_button.setEnabled(ready > 0)
        self.pages.setCurrentIndex(1 if items else 0)
        if items:
            index = next((n for n, i in enumerate(items) if i.file_id == current_id), 0)
            self.queue.setCurrentRow(index)
            self._row_changed(index)

    def current_item(self) -> QueueItem | None:
        row = self.queue.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def _values(self, item: QueueItem) -> tuple[str, str]:
        edit = self._edits.get(item.file_id, {})
        p = item.proposal
        return edit.get("name", p.new_name if p else ""), edit.get("folder", p.target_folder if p else "")

    def _row_changed(self, row: int) -> None:
        for n in range(self.queue.count()):
            widget = self.queue.itemWidget(self.queue.item(n))
            if widget:
                widget.set_selected(n == row)
        item = self.current_item()
        self.detail.show_item(item, *(self._values(item) if item else ("", "")))

    def _detail_edited(self) -> None:
        item = self.current_item()
        if item:
            self._edits.setdefault(item.file_id, {}).update(name=self.detail.name.text().strip(),
                                                           folder=self.detail.folder.text().strip())

    def _apply_alternative(self, index: int) -> None:
        item = self.current_item()
        if not item or not item.proposal or index >= len(item.proposal.alternatives):
            return
        alt = item.proposal.alternatives[index]
        self._edits[item.file_id] = {"name": alt.new_name, "folder": alt.target_folder, "alt": index}
        self.detail.show_item(item, alt.new_name, alt.target_folder)

    # --- actions ------------------------------------------------------------------------------

    def _validation(self, item: QueueItem) -> Validation | None:
        p = item.proposal
        if item.status != "ready" or not p:
            return None
        name, folder_text = self._values(item)
        folder = normalize_rel(folder_text)
        if not folder or not name:
            return None
        alt = self._edits.get(item.file_id, {}).get("alt")
        if alt is not None and (folder, name) == (p.alternatives[alt].target_folder, p.alternatives[alt].new_name):
            decision = "alternative_chosen"
        elif (folder, name) == (p.target_folder, p.new_name):
            decision = "accepted"
        else:
            decision = "edited"
        return Validation(item.file_id, folder, name, decision)

    def validate_selected(self) -> None:
        item = self.current_item()
        if item:
            self._validate([item])

    def validate_all(self) -> None:
        self._validate(self.items, force_simulation=True)

    def _validate(self, items: list[QueueItem], force_simulation: bool = False) -> None:
        for item in items:
            name = self._values(item)[0]
            if item.status == "ready" and name and not is_valid_name(name):
                QMessageBox.warning(self, "Nom invalide", f"« {name} » n'est pas utilisable sous Windows ou macOS.")
                return
        validations = [v for v in (self._validation(i) for i in items) if v]
        if not validations:
            QMessageBox.information(self, "TriBin", "Aucun fichier prêt à ranger : complète le nom et le dossier, "
                                    "ou attends la fin de l'analyse.")
            return
        self.c.validate(validations, force_simulation)

    def edit_name(self) -> None:
        self.detail.name.setFocus()
        self.detail.name.selectAll()

    def pick_folder(self) -> None:
        item = self.current_item()
        if not item or not item.proposal:
            return
        root = Path(item.root)
        start = root / self._values(item)[1]
        chosen = QFileDialog.getExistingDirectory(self, "Choisir le dossier de rangement",
                                                  str(start if start.is_dir() else root))
        if not chosen:
            return
        if not is_within(Path(chosen), root):
            QMessageBox.warning(self, "Hors racine", f"Choisis un dossier à l'intérieur de {root}.")
            return
        self.detail.folder.setText(Path(chosen).resolve().relative_to(root.resolve()).as_posix())

    def choose_alternative(self) -> None:
        item = self.current_item()
        if item and item.proposal and item.proposal.alternatives:
            self._apply_alternative(0)
        else:
            self.statusBar().showMessage("Pas d'autre piste pour ce fichier.", 4000)

    def skip(self) -> None:
        row = self.queue.currentRow()
        if row + 1 < len(self.items):
            self.queue.setCurrentRow(row + 1)

    def return_selected(self) -> None:
        item = self.current_item()
        if item:
            self.c.return_to_origin(item.file_id)

    # --- glisser-déposer ----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.c.drop_paths(paths)
