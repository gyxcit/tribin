"""Fenêtre Corbeille : fichiers en attente et propositions ; valider, modifier, alternatives, renvoyer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tribin.config import is_within
from tribin.convention.naming import is_valid_name
from tribin.engine.proposer import normalize_rel
from tribin.service.bin import Validation
from tribin.service.queue import QueueItem
from tribin.ui.drop_widget import dropped_paths
from tribin.ui.icons import bin_icon

if TYPE_CHECKING:
    from tribin.ui.app import AppController

COL_THUMB, COL_ORIGINAL, COL_NAME, COL_FOLDER, COL_CONF = range(5)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def thumbnail(path: Path, size: int = 40) -> QPixmap:
    if path.suffix.lower() in IMAGE_EXT and path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QFileIconProvider().icon(QFileInfo(str(path))).pixmap(size, size)


def confidence_text(item: QueueItem) -> tuple[str, str]:
    if item.status == "analyzing":
        return "Analyse…", "#888"
    if item.status == "error":
        return "Erreur", "#c0392b"
    p = item.proposal
    if p is None or p.manual:
        return "À traiter", "#c0392b"
    color = "#1e8e3e" if p.confidence >= 0.8 else "#b7791f" if p.confidence >= 0.6 else "#c0392b"
    return f"{p.confidence:.0%}" + (" · à vérifier" if p.needs_review else ""), color


class BinWindow(QMainWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.items: list[QueueItem] = []
        self._chosen_alt: dict[str, int] = {}
        self._filling = False
        self.setWindowTitle("TriBin — Corbeille")
        self.setWindowIcon(bin_icon())
        self.setAcceptDrops(True)
        self.resize(1100, 520)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Fichier d'origine", "Nom proposé", "Dossier proposé", "Confiance"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_THUMB, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_THUMB, 50)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._cell_edited)

        self.empty = QLabel("Glisse des fichiers ici ou sur le widget flottant pour les ranger.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: #888; font-size: 15px; padding: 30px;")

        buttons = QHBoxLayout()
        for label, slot, tip in [
            ("Valider (Entrée)", self.validate_selected, "Ranger les fichiers sélectionnés"),
            ("Éditer le nom (E)", self.edit_name, "Modifier le nom proposé"),
            ("Choisir un dossier…", self.pick_folder, "Choisir un dossier dans les racines"),
            ("Alternatives (A)", self.choose_alternative, "Voir les autres propositions"),
            ("Renvoyer (R)", self.return_selected, "Renvoyer à l'emplacement d'origine"),
            ("Tout valider", self.validate_all, "Ranger tous les fichiers prêts (avec simulation)"),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch()
        hist = QPushButton("Historique")
        hist.clicked.connect(self.c.show_history)
        buttons.addWidget(hist)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.empty)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.setCentralWidget(central)

        for key, slot in [(Qt.Key.Key_Return, self.validate_selected), (Qt.Key.Key_Enter, self.validate_selected),
                          (Qt.Key.Key_E, self.edit_name), (Qt.Key.Key_A, self.choose_alternative),
                          (Qt.Key.Key_Escape, self.skip), (Qt.Key.Key_R, self.return_selected)]:
            sc = QShortcut(QKeySequence(key), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    # --- affichage ----------------------------------------------------------------------------

    def refresh(self, items: list[QueueItem]) -> None:
        selected = {self.items[i.row()].file_id for i in self.table.selectionModel().selectedRows() if i.row() < len(self.items)}
        self.items = items
        self._filling = True
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            p = item.proposal
            thumb = QTableWidgetItem()
            thumb.setData(Qt.ItemDataRole.DecorationRole, thumbnail(Path(item.staged_path)))
            thumb.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, COL_THUMB, thumb)
            original = QTableWidgetItem(Path(item.original_path).name)
            original.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            original.setToolTip(item.original_path)
            self.table.setItem(row, COL_ORIGINAL, original)
            name = QTableWidgetItem(p.new_name if p else "")
            folder = QTableWidgetItem((p.target_folder + (" (nouveau)" if p.folder_is_new else "")) if p else "")
            tip = self._tooltip(item)
            for cell in (name, folder):
                cell.setToolTip(tip)
                if not p:
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, COL_NAME, name)
            self.table.setItem(row, COL_FOLDER, folder)
            text, color = confidence_text(item)
            conf = QTableWidgetItem(text)
            conf.setForeground(QColor(color))
            conf.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            conf.setToolTip(tip)
            self.table.setItem(row, COL_CONF, conf)
            if item.file_id in selected:
                self.table.selectRow(row)
        self._filling = False
        self.empty.setVisible(not items)
        self.table.setVisible(bool(items))
        if items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)

    @staticmethod
    def _tooltip(item: QueueItem) -> str:
        if item.status == "error":
            return item.error or "Erreur"
        p = item.proposal
        if not p:
            return "Analyse en cours…"
        lines = [f"Pourquoi : {p.reasoning}"] if p.reasoning else []
        lines += [f"⚠ {w}" for w in p.warnings]
        if item.error:
            lines.append(f"⚠ {item.error}")
        return "\n".join(lines) or "—"

    def _cell_edited(self, cell: QTableWidgetItem) -> None:
        if self._filling or cell.column() not in (COL_NAME, COL_FOLDER):
            return
        item = self.items[cell.row()]
        if not item.proposal:
            return
        if cell.column() == COL_NAME and not is_valid_name(cell.text().strip()):
            QMessageBox.warning(self, "Nom invalide", "Ce nom n'est pas utilisable sous Windows ou macOS.")
            self.refresh(self.items)

    # --- actions ------------------------------------------------------------------------------

    def _rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def _validation(self, row: int) -> Validation | None:
        item = self.items[row]
        p = item.proposal
        if item.status != "ready" or not p:
            return None
        name = self.table.item(row, COL_NAME).text().strip()
        folder_text = self.table.item(row, COL_FOLDER).text().replace(" (nouveau)", "").strip()
        folder = normalize_rel(folder_text)
        if not folder or not name:
            return None
        alt = self._chosen_alt.get(item.file_id)
        if alt is not None and (folder, name) == (p.alternatives[alt].target_folder, p.alternatives[alt].new_name):
            decision = "alternative_chosen"
        elif (folder, name) == (p.target_folder, p.new_name):
            decision = "accepted"
        else:
            decision = "edited"
        return Validation(item.file_id, folder, name, decision)

    def validate_selected(self) -> None:
        self._validate(self._rows())

    def validate_all(self) -> None:
        self._validate(list(range(len(self.items))), force_simulation=True)

    def _validate(self, rows: list[int], force_simulation: bool = False) -> None:
        validations = [v for v in (self._validation(r) for r in rows) if v]
        if not validations:
            QMessageBox.information(self, "TriBin", "Aucun fichier prêt à ranger dans la sélection "
                                    "(proposition manquante, à traiter manuellement ou dossier vide).")
            return
        self.c.validate(validations, force_simulation)

    def edit_name(self) -> None:
        rows = self._rows()
        if rows:
            self.table.editItem(self.table.item(rows[0], COL_NAME))

    def pick_folder(self) -> None:
        rows = self._rows()
        if not rows or not self.items[rows[0]].proposal:
            return
        item = self.items[rows[0]]
        root = Path(item.root)
        start = root / item.proposal.target_folder
        chosen = QFileDialog.getExistingDirectory(self, "Choisir le dossier de rangement",
                                                  str(start if start.is_dir() else root))
        if not chosen:
            return
        if not is_within(Path(chosen), root):
            QMessageBox.warning(self, "Hors racine", f"Choisis un dossier à l'intérieur de {root}.")
            return
        rel = Path(chosen).resolve().relative_to(root.resolve()).as_posix()
        self.table.item(rows[0], COL_FOLDER).setText(rel)

    def choose_alternative(self) -> None:
        rows = self._rows()
        if not rows or not self.items[rows[0]].proposal or not self.items[rows[0]].proposal.alternatives:
            QMessageBox.information(self, "TriBin", "Pas d'alternative pour ce fichier.")
            return
        item = self.items[rows[0]]
        alts = item.proposal.alternatives
        labels = [f"{a.target_folder}/{a.new_name} — {a.reasoning}" for a in alts]
        choice, ok = QInputDialog.getItem(self, "Alternatives", "Choisir une autre proposition :", labels, 0, False)
        if ok:
            index = labels.index(choice)
            self._chosen_alt[item.file_id] = index
            self.table.item(rows[0], COL_NAME).setText(alts[index].new_name)
            self.table.item(rows[0], COL_FOLDER).setText(alts[index].target_folder)

    def skip(self) -> None:
        rows = self._rows()
        if rows and rows[-1] + 1 < len(self.items):
            self.table.selectRow(rows[-1] + 1)

    def return_selected(self) -> None:
        for row in self._rows():
            self.c.return_to_origin(self.items[row].file_id)

    # --- glisser-déposer ----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.c.drop_paths(paths)
