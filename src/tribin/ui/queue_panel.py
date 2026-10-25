"""Colonne centrale : titre, recherche, onglets Tous / À vérifier / Prêts, liste groupée et « Ranger les N prêts »."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tribin.service.queue import QueueItem
from tribin.ui.components import FileBadge, KeyButton, Pill, elided, item_level, status_label
from tribin.ui.icons import line_icon

GROUPS = (("check", "À vérifier"), ("wait", "Analyse en cours"), ("ready", "Prêts à ranger"))
TABS = (("all", "Tous"), ("check", "À vérifier"), ("ready", "Prêts"), ("aside", "Mis de côté"))
TEXT_WIDTH = 180


def group_of(item: QueueItem) -> str:
    key = item_level(item)[0]
    return "wait" if key == "wait" else "check" if key == "check" else "ready"


def destination_text(item: QueueItem) -> str:
    if item.status == "analyzing":
        return "Analyse en cours…"
    p = item.proposal
    if item.status == "error" or p is None or p.manual or not p.target_folder:
        return "Aucune piste fiable : à ranger à la main"
    return " › ".join(x for x in p.target_folder.split("/") if x)


class QueueRow(QFrame):
    """Ligne : type de fichier, nom d'origine, destination proposée, statut."""

    def __init__(self, item: QueueItem):
        super().__init__()
        self.setObjectName("QueueRow")
        self.file_id = item.file_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(17, 10, 16, 10)
        layout.setSpacing(12)
        badge = FileBadge(36)
        badge.set_path(Path(item.original_path))
        layout.addWidget(badge)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        original = Path(item.original_path).name
        name = QLabel()
        name.setStyleSheet("font-weight: 500;")
        name.setText(elided(original, name, TEXT_WIDTH))
        name.setToolTip(original)
        where = QLabel()
        where.setObjectName("Muted")
        dest = destination_text(item)
        where.setText(elided(dest, where, TEXT_WIDTH))
        where.setToolTip(dest)
        texts.addWidget(name)
        texts.addWidget(where)
        layout.addLayout(texts, 1)
        _, _, background, text = item_level(item)
        label = "Mis de côté" if item.status == "skipped" else status_label(item)
        colors = ("#ECEEF4", "#5B6080") if item.status == "skipped" else (background, text)
        layout.addWidget(Pill(label, colors), 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class QueuePanel(QFrame):
    selection_changed = Signal(str)
    validate_all_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Pane")
        self.items: list[QueueItem] = []
        self.aside: list[QueueItem] = []  # mis de côté : onglet à part, hors des compteurs
        self.order: list[str] = []  # file_id dans l'ordre d'affichage
        self.tab = "all"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QWidget()
        top = QVBoxLayout(head)
        top.setContentsMargins(20, 20, 20, 12)
        top.setSpacing(2)
        title = QLabel("À ranger")
        title.setObjectName("Title")
        self.refresh_button = QPushButton("Actualiser")
        self.refresh_button.setObjectName("Ghost")
        self.refresh_button.setIcon(line_icon("refresh"))
        self.refresh_button.setIconSize(QSize(16, 16))
        self.refresh_button.setToolTip("Relit la clé API et les réglages, relance les analyses restées sans IA (F5)")
        self.refresh_button.clicked.connect(self.refresh_clicked)
        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.refresh_button)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        top.addLayout(title_row)
        top.addWidget(self.summary)
        top.addSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Rechercher un fichier")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._rebuild(self.current_file_id()))
        top.addWidget(self.search)
        layout.addWidget(head)

        tabs = QFrame()
        tabs.setObjectName("PaneHead")
        tab_row = QHBoxLayout(tabs)
        tab_row.setContentsMargins(14, 0, 14, 0)
        tab_row.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, _ in TABS:
            button = QPushButton()
            button.setObjectName("Tab")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            self.tab_group.addButton(button)
            self.tab_buttons[key] = button
            tab_row.addWidget(button)
        tab_row.addStretch()
        self.tab_buttons["all"].setChecked(True)
        layout.addWidget(tabs)

        self.list = QListWidget()
        self.list.setObjectName("Queue")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self._row_changed)
        layout.addWidget(self.list, 1)
        self.empty = QLabel()  # onglet ou recherche sans résultat : un message plutôt qu'une liste vide
        self.empty.setObjectName("Empty")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setContentsMargins(24, 32, 24, 32)
        self.empty.hide()
        layout.addWidget(self.empty, 1)

        foot = QFrame()
        foot.setObjectName("PaneFoot")
        foot_row = QHBoxLayout(foot)
        foot_row.setContentsMargins(20, 12, 20, 12)
        self.ready_note = QLabel()
        self.ready_note.setObjectName("Muted")
        self.ready_note.setToolTip("Une simulation montre tout avant le moindre déplacement.")
        foot_row.addWidget(self.ready_note, 1)
        self.validate_all = KeyButton("Ranger les prêts", "", "Primary")
        self.validate_all.setToolTip("Une simulation montre tout avant le moindre déplacement.")
        self.validate_all.clicked.connect(self.validate_all_clicked)
        foot_row.addWidget(self.validate_all)
        layout.addWidget(foot)
        self._update_tabs()

    # --- contenu ------------------------------------------------------------------------------

    def set_items(self, items: list[QueueItem], current_id: str | None, aside: list[QueueItem] | None = None) -> None:
        self.items = items
        self.aside = list(aside or [])
        if self.tab == "aside" and not self.aside:
            self.tab = "all"
        elif not items and self.aside:
            self.tab = "aside"
        self.tab_buttons[self.tab].setChecked(True)
        groups = [group_of(i) for i in items]
        ready, check = groups.count("ready"), groups.count("check") + groups.count("wait")
        plural = "s" if len(items) > 1 else ""
        self.summary.setText(f"{len(items)} fichier{plural} déposé{plural} · {ready} prêt{'s' if ready > 1 else ''}, "
                             f"{check} à vérifier")
        self.ready_note.setText(f"{ready} prêt{'s' if ready > 1 else ''} à ranger" if ready else "Rien de prêt pour l'instant")
        self.validate_all.label.setText(f"Ranger les {ready} prêts" if ready > 1 else "Ranger le fichier prêt")
        self.validate_all.setEnabled(ready > 0)
        self._update_tabs()
        self._rebuild(current_id)

    def _update_tabs(self) -> None:
        groups = [group_of(i) for i in self.items]
        counts = {"all": len(groups), "check": groups.count("check") + groups.count("wait"),
                  "ready": groups.count("ready"), "aside": len(self.aside)}
        for key, label in TABS:
            self.tab_buttons[key].setText(f"{label}  {counts[key]}")
        self.tab_buttons["aside"].setVisible(bool(self.aside))

    def set_tab(self, key: str) -> None:
        self.tab = key
        self.tab_buttons[key].setChecked(True)
        self._rebuild(self.current_file_id())

    def _in_tab(self, item: QueueItem) -> bool:
        group = group_of(item)
        return self.tab == "all" or (self.tab == "ready") == (group == "ready")

    def _rebuild(self, current_id: str | None) -> None:
        needle = self.search.text().strip().casefold()
        source = self.aside if self.tab == "aside" else [i for i in self.items if self._in_tab(i)]
        visible = [i for i in source if not needle or needle in Path(i.original_path).name.casefold()
                   or needle in (i.proposal.new_name.casefold() if i.proposal else "")]
        groups = (("aside", "Mis de côté : ni comptés ni rangés automatiquement"),) if self.tab == "aside" else GROUPS
        self.list.blockSignals(True)
        self.list.clear()
        self.order = []
        for key, title in groups:
            members = [i for i in visible if key == "aside" or group_of(i) == key]
            if not members:
                continue
            header = QListWidgetItem()
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            caption = QLabel(title)
            caption.setObjectName("GroupTitle")
            caption.setContentsMargins(20, 14, 20, 4)
            header.setSizeHint(caption.sizeHint())
            self.list.addItem(header)
            self.list.setItemWidget(header, caption)
            for item in members:
                widget = QueueRow(item)
                entry = QListWidgetItem()
                entry.setData(Qt.ItemDataRole.UserRole, item.file_id)
                entry.setSizeHint(widget.sizeHint())
                self.list.addItem(entry)
                self.list.setItemWidget(entry, widget)
                self.order.append(item.file_id)
        self.list.blockSignals(False)
        self.empty.setText(self._empty_text(needle))
        self.empty.setVisible(not self.order)
        self.list.setVisible(bool(self.order))
        target = current_id if current_id in self.order else (self.order[0] if self.order else None)
        if target:
            self.select_file(target)
        else:
            self.selection_changed.emit("")

    def _empty_text(self, needle: str) -> str:
        if needle:
            return "Aucun fichier ne correspond à la recherche."
        return {
            "ready": "Aucun fichier prêt pour l'instant.\nLes propositions sûres apparaissent ici ; les autres attendent "
                     "votre avis dans « À vérifier ».",
            "check": "Rien à vérifier : toutes les propositions sont prêtes.",
            "aside": "Aucun fichier mis de côté.",
        }.get(self.tab, "Aucun fichier déposé.")

    # --- sélection ----------------------------------------------------------------------------

    def _row_of(self, file_id: str) -> int:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == file_id:
                return row
        return -1

    def select_file(self, file_id: str) -> None:
        row = self._row_of(file_id)
        aside = any(i.file_id == file_id for i in self.aside)
        if row < 0 and (aside or any(i.file_id == file_id for i in self.items)):  # caché par l'onglet ou la recherche
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.tab = "aside" if aside else "all"
            self.tab_buttons[self.tab].setChecked(True)
            self._rebuild(file_id)
            return
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
