"""Fenêtre principale, en trois colonnes : navigation, fichiers à ranger, proposition détaillée."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from tribin.ui.bin_detail import DetailPanel
from tribin.ui.components import divider
from tribin.ui.drop_widget import dropped_paths
from tribin.ui.icons import app_icon, logo_pixmap
from tribin.ui.queue_panel import QueuePanel

if TYPE_CHECKING:
    from tribin.ui.app import AppController

PROVIDER_NAMES = {"anthropic": "Claude", "gemini": "Gemini", "mistral": "Mistral"}


def nav_item(text: str, checkable: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("NavItem")
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class BinWindow(QMainWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.items: list[QueueItem] = []
        self.aside: list[QueueItem] = []  # mis de côté
        self._edits: dict[str, dict] = {}  # file_id -> {"name", "folder", "alt"} modifiés par l'utilisateur
        self.setWindowTitle("TriBin")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(1280, 800)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._bin_page())
        from tribin.ui.history import HistoryView

        self.history = HistoryView(controller)
        self.pages.addWidget(self.history)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.statusBar()

        for key, slot in [(Qt.Key.Key_Return, self.validate_selected), (Qt.Key.Key_Enter, self.validate_selected),
                          (Qt.Key.Key_E, self.edit_name), (Qt.Key.Key_A, self.choose_alternative),
                          (Qt.Key.Key_Escape, self.skip), (Qt.Key.Key_R, self.return_selected)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda s=slot: self._shortcut(s))
        refresh = QShortcut(QKeySequence(QKeySequence.StandardKey.Refresh), self)  # F5 (Cmd+R sur macOS)
        refresh.activated.connect(self.c.refresh_all)

    # --- construction -------------------------------------------------------------------------

    def _sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(224)
        col = QVBoxLayout(side)
        col.setContentsMargins(12, 16, 12, 12)
        col.setSpacing(2)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 4, 8, 16)
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(28))
        brand = QLabel("TriBin")
        brand.setObjectName("Brand")
        brand_row.addWidget(logo)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        col.addLayout(brand_row)
        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, label in (("bin", "À ranger"), ("history", "Historique")):
            button = nav_item(label, checkable=True)
            button.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav.addButton(button)
            self.nav_buttons[key] = button
            col.addWidget(button)
        self.pending_count = QLabel()
        self.pending_count.setObjectName("NavCount")
        self.pending_count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        count_row = QHBoxLayout(self.nav_buttons["bin"])
        count_row.setContentsMargins(0, 0, 10, 0)
        count_row.addStretch()
        count_row.addWidget(self.pending_count)
        col.addStretch()
        col.addWidget(divider())
        col.addSpacing(8)
        settings = nav_item("Réglages")
        settings.clicked.connect(self.c.show_settings)
        col.addWidget(settings)
        self.ai_chip = QLabel()
        self.ai_chip.setObjectName("AiStatus")
        self.ai_chip.setTextFormat(Qt.TextFormat.RichText)
        col.addWidget(self.ai_chip)
        self.nav_buttons["bin"].setChecked(True)
        return side

    def _bin_page(self) -> QWidget:
        self.queue = QueuePanel()
        self.queue.setFixedWidth(380)
        self.queue.selection_changed.connect(self._selection_changed)
        self.queue.validate_all_clicked.connect(self.validate_all)
        self.queue.refresh_clicked.connect(self.c.refresh_all)
        self.detail = DetailPanel()
        self.detail.edited.connect(self._detail_edited)
        self.detail.alternative_chosen.connect(self._apply_alternative)
        self.detail.validate_clicked.connect(self.validate_selected)
        self.detail.return_clicked.connect(self.return_selected)
        self.detail.skip_clicked.connect(self.skip)
        self.detail.browse_clicked.connect(self.pick_folder)
        self.detail.reanalyze_clicked.connect(self.reanalyze_selected)
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.queue)
        layout.addWidget(self.detail, 1)

        empty = QWidget()
        column = QVBoxLayout(empty)
        column.setSpacing(8)
        column.addStretch()
        big_logo = QLabel()
        big_logo.setPixmap(logo_pixmap(72))
        big_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Tout est rangé")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message = QLabel("Glissez de nouveaux fichiers sur le widget ou sur cette fenêtre :\n"
                         "TriBin vous proposera où les ranger.")
        message.setObjectName("Empty")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        to_history = QPushButton("Voir l'historique")
        to_history.clicked.connect(lambda: self.show_page("history"))
        for widget in (big_logo, title, message):
            column.addWidget(widget)
        column.addSpacing(8)
        column.addWidget(to_history, 0, Qt.AlignmentFlag.AlignCenter)
        column.addStretch()

        self.bin_pages = QStackedWidget()
        self.bin_pages.addWidget(empty)
        self.bin_pages.addWidget(body)
        return self.bin_pages

    def show_page(self, key: str) -> None:
        self.nav_buttons[key].setChecked(True)
        if key == "history":
            self.history.reload()
            self.pages.setCurrentWidget(self.history)
        else:
            self.pages.setCurrentWidget(self.bin_pages)

    # --- affichage ----------------------------------------------------------------------------

    def refresh(self, items: list[QueueItem], aside: list[QueueItem] | None = None) -> None:
        current = self.queue.current_file_id()
        self.items = items
        self.aside = aside or []
        known = {i.file_id for i in [*items, *self.aside]}
        self._edits = {k: v for k, v in self._edits.items() if k in known}
        self.pending_count.setText(str(len(items)) if items else "")
        self._update_ai_chip()
        self.bin_pages.setCurrentIndex(1 if items or self.aside else 0)
        self.queue.set_items(items, current, self.aside)

    def _update_ai_chip(self) -> None:
        try:
            settings = self.c.service.ai_settings()
            name = PROVIDER_NAMES.get(settings.provider, settings.provider)
            ok = bool(settings.api_key)
            text = f"IA : {name}" if ok else f"IA : {name}, clé manquante"
            tip = f"Modèle : {settings.model}. Modifiable dans les Réglages."
        except Exception:
            ok, text, tip = False, "IA non configurée", "À configurer dans les Réglages."
        color = "#14B8A6" if ok else "#F0605A"
        self.ai_chip.setText(f'<span style="color:{color}">●</span>&nbsp; {text}')
        self.ai_chip.setToolTip(tip)

    def current_item(self) -> QueueItem | None:
        file_id = self.queue.current_file_id()
        return next((i for i in [*self.items, *self.aside] if i.file_id == file_id), None)

    def select_file(self, file_id: str) -> None:
        self.queue.select_file(file_id)

    def _categories(self) -> list[str]:
        try:
            return self.c.service.convention().category_codes()
        except Exception:
            return []

    def _values(self, item: QueueItem) -> tuple[str, str]:
        edit = self._edits.get(item.file_id, {})
        p = item.proposal
        return edit.get("name", p.new_name if p else ""), edit.get("folder", p.target_folder if p else "")

    def _selection_changed(self, file_id: str) -> None:
        item = self.current_item() if file_id else None
        self.detail.show_item(item, *(self._values(item) if item else ("", "")), categories=self._categories())

    def _detail_edited(self) -> None:
        item = self.current_item()
        if item:
            self._edits.setdefault(item.file_id, {}).update(name=self.detail.name.text().strip(),
                                                           folder=self.detail.folder)

    def _apply_alternative(self, index: int) -> None:
        item = self.current_item()
        if not item or not item.proposal or index >= len(item.proposal.alternatives):
            return
        alt = item.proposal.alternatives[index]
        self._edits[item.file_id] = {"name": alt.new_name, "folder": alt.target_folder, "alt": index}
        self.detail.show_item(item, alt.new_name, alt.target_folder, categories=self._categories())

    # --- actions ------------------------------------------------------------------------------

    def _shortcut(self, slot) -> None:
        """Raccourcis inactifs pendant la saisie d'un texte (le nom, la recherche)."""
        if isinstance(QApplication.focusWidget(), QLineEdit) or self.pages.currentWidget() is not self.bin_pages:
            return
        slot()

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
        from tribin.ui.queue_panel import group_of

        self._validate([i for i in self.items if group_of(i) == "ready"], force_simulation=True)

    def _validate(self, items: list[QueueItem], force_simulation: bool = False) -> None:
        for item in items:
            name = self._values(item)[0]
            if item.status == "ready" and name and not is_valid_name(name):
                QMessageBox.warning(self, "Nom invalide", f"« {name} » n'est pas utilisable sous Windows ou macOS.")
                return
        validations = [v for v in (self._validation(i) for i in items) if v]
        if not validations:
            QMessageBox.information(self, "TriBin", "Aucun fichier prêt à ranger : complétez le nom et le dossier, "
                                    "ou attendez la fin de l'analyse.")
            return
        self.c.validate(validations, force_simulation)

    def edit_name(self) -> None:
        self.detail.focus_name()

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
            QMessageBox.warning(self, "Hors racine", f"Choisissez un dossier à l'intérieur de {root}.")
            return
        self.detail.set_folder(Path(chosen).resolve().relative_to(root.resolve()).as_posix())

    def choose_alternative(self) -> None:
        item = self.current_item()
        if item and item.proposal and item.proposal.alternatives:
            self._apply_alternative(0)
        else:
            self.statusBar().showMessage("Pas d'autre piste pour ce fichier.", 4000)

    def skip(self) -> None:
        """« Mettre de côté » (Échap) ; sur un fichier déjà mis de côté : « Remettre à ranger »."""
        item = self.current_item()
        if item is None:
            return
        if item.status == "skipped":
            self.c.resume(item.file_id)
        else:
            self.c.set_aside(item.file_id)

    def reanalyze_selected(self) -> None:
        item = self.current_item()
        if item:
            self._edits.pop(item.file_id, None)  # la nouvelle proposition remplace les modifications en cours
            self.c.reanalyze(item.file_id)

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
