"""Colonne de droite : le fichier sélectionné, la proposition de l'IA (nom, dossier, catégorie, confiance),
les autres possibilités et la barre d'actions."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tribin.service.queue import QueueItem
from tribin.ui.components import (
    Breadcrumb,
    ConfidenceBar,
    KeyButton,
    Pill,
    divider,
    elided,
    human_size,
    item_level,
    muted,
    section,
    thumbnail,
)
from tribin.ui.theme import mono_font

HESITATION = "L'IA hésite avec"
NEW_VERSION = "Nouvelle version"
LEVEL_COLORS = {"sure": "#14B8A6", "look": "#F5A524", "check": "#F0605A", "wait": "#C9CDE6"}


def category_label(code: str) -> str:
    """« 02_Creation » -> « Creation » : libellé court d'une catégorie de la convention."""
    return code.split("_", 1)[-1].replace("-", " ") if "_" in code else code


def level_text(item: QueueItem) -> str:
    if item.status == "analyzing":
        return "Analyse en cours…"
    if item.status == "error":
        return "Erreur d'analyse"
    p = item.proposal
    if p is None or p.manual:
        return "À traiter à la main"
    return f"{item_level(item)[1]} · {p.confidence:.0%}".replace("%", " %")


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


class DetailPanel(QFrame):
    """Proposition du fichier sélectionné ; nom, dossier et catégorie se modifient directement."""

    edited = Signal()
    alternative_chosen = Signal(int)
    validate_clicked = Signal()
    return_clicked = Signal()
    skip_clicked = Signal()
    browse_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.item: QueueItem | None = None
        self._folder = ""
        self._categories: list[str] = []
        self._filling = False

        # --- en-tête : le fichier ---
        head = QFrame()
        head.setObjectName("PaneHead")
        top = QHBoxLayout(head)
        top.setContentsMargins(28, 20, 20, 16)
        top.setSpacing(16)
        self.preview = QLabel()
        self.preview.setFixedSize(56, 56)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #F6F7FB; border-radius: 8px;")
        top.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.original = QLabel()
        self.original.setObjectName("Title")
        self.original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta = muted(wrap=False)
        titles.addWidget(self.original)
        titles.addWidget(self.meta)
        top.addLayout(titles, 1)
        self.open_button = QPushButton("Ouvrir")
        self.open_button.setObjectName("Ghost")
        self.open_button.clicked.connect(self._open_file)
        self.reveal_button = QPushButton("Afficher dans le dossier")
        self.reveal_button.setObjectName("Ghost")
        self.reveal_button.clicked.connect(self._reveal_file)
        top.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.reveal_button, 0, Qt.AlignmentFlag.AlignTop)

        # --- la proposition de l'IA ---
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(28, 20, 28, 20)
        body.setSpacing(0)

        card = QFrame()
        card.setObjectName("SuggestCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 14, 18, 16)
        inner.setSpacing(12)
        card_head = QHBoxLayout()
        star = QLabel("✦")
        star.setStyleSheet("color: #F5A524; font-size: 14px;")
        card_title = QLabel("Proposition de l'IA")
        card_title.setStyleSheet("font-weight: 600; color: #5B6080;")
        self.note = Pill(colors=("#E8EAF6", "#2C3460"))
        card_head.addWidget(star)
        card_head.addWidget(card_title)
        card_head.addStretch()
        card_head.addWidget(self.note)
        inner.addLayout(card_head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnMinimumWidth(0, 110)
        grid.setColumnStretch(1, 1)
        grid.addWidget(field_label("Nouveau nom"), 0, 0)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name = QLineEdit()
        self.name.setObjectName("NewName")
        self.name.setFont(mono_font())
        self.name.setAccessibleName("Nouveau nom")
        self.name.setToolTip("Raccourci : E")
        self.name.textChanged.connect(self._changed)
        self.name.returnPressed.connect(self.validate_clicked)
        name_row.addWidget(self.name, 1)
        grid.addLayout(name_row, 0, 1)

        grid.addWidget(field_label("Dossier"), 1, 0)
        crumb_row = QHBoxLayout()
        crumb_row.setSpacing(10)
        self.breadcrumb = Breadcrumb()
        self.browse = QPushButton("Changer…")
        self.browse.setObjectName("Link")
        self.browse.clicked.connect(self.browse_clicked)
        crumb_row.addWidget(self.breadcrumb)
        crumb_row.addWidget(self.browse)
        crumb_row.addStretch()
        grid.addLayout(crumb_row, 1, 1)

        grid.addWidget(field_label("Catégorie"), 2, 0)
        self.category = QComboBox()
        self.category.setMinimumWidth(200)
        self.category.setAccessibleName("Catégorie")
        self.category.activated.connect(self._category_chosen)
        cat_row = QHBoxLayout()
        cat_row.addWidget(self.category)
        cat_row.addStretch()
        grid.addLayout(cat_row, 2, 1)

        grid.addWidget(field_label("Confiance"), 3, 0)
        conf_row = QHBoxLayout()
        conf_row.setSpacing(10)
        self.bar = ConfidenceBar()
        self.pill = QLabel()
        self.pill.setStyleSheet("font-weight: 500;")
        conf_row.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignVCenter)
        conf_row.addWidget(self.pill)
        conf_row.addStretch()
        grid.addLayout(conf_row, 3, 1)
        inner.addLayout(grid)

        inner.addWidget(divider())
        self.reasoning = QLabel()
        self.reasoning.setWordWrap(True)
        self.reasoning.setStyleSheet("color: #3A4063;")
        self.reasoning.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner.addWidget(self.reasoning)
        self.warnings = QLabel()
        self.warnings.setObjectName("Warning")
        self.warnings.setWordWrap(True)
        inner.addWidget(self.warnings)
        body.addWidget(card)

        # --- autres possibilités ---
        body.addSpacing(24)
        self.alt_title = section("Autres possibilités")
        body.addWidget(self.alt_title)
        body.addSpacing(6)
        self.alt_rows = [self._alt_row(index) for index in range(2)]  # créées une fois, réutilisées
        for row, _, _ in self.alt_rows:
            body.addWidget(row)
        body.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # --- actions ---
        actions = QFrame()
        actions.setObjectName("PaneFoot")
        bar = QHBoxLayout(actions)
        bar.setContentsMargins(20, 12, 28, 12)
        bar.setSpacing(8)
        self.return_button = KeyButton("Renvoyer à l'origine", "R", "Ghost")
        self.return_button.clicked.connect(self.return_clicked)
        self.skip_button = KeyButton("Passer", "Échap")
        self.skip_button.clicked.connect(self.skip_clicked)
        self.validate_button = KeyButton("Ranger ici", "Entrée", "Primary")
        self.validate_button.clicked.connect(self.validate_clicked)
        bar.addWidget(self.return_button)
        bar.addStretch()
        bar.addWidget(self.skip_button)
        bar.addWidget(self.validate_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(head)
        outer.addWidget(scroll, 1)
        outer.addWidget(actions)

    # --- valeurs ------------------------------------------------------------------------------

    @property
    def folder(self) -> str:
        return self._folder

    def set_folder(self, folder: str) -> None:
        self._folder = folder.strip().strip("/")
        parts = [p for p in self._folder.split("/") if p]
        self.breadcrumb.set_parts(parts)
        current = parts[-1] if parts else ""
        index = self.category.findData(current)
        self.category.setCurrentIndex(index)
        self.category.setEnabled(index >= 0 and self.name.isEnabled())
        self._changed()

    def focus_name(self) -> None:
        self.name.setFocus()
        self.name.selectAll()

    def _changed(self) -> None:
        if not self._filling:
            self.edited.emit()

    def _category_chosen(self, index: int) -> None:
        code = self.category.itemData(index)
        parts = [p for p in self._folder.split("/") if p]
        if code and parts and parts[-1] in self._categories:
            parts[-1] = code
            self.set_folder("/".join(parts))

    def _build_categories(self, categories: list[str]) -> None:
        if categories == self._categories:
            return
        self._categories = categories
        self.category.clear()
        for code in categories:
            self.category.addItem(category_label(code), code)
            self.category.setItemData(self.category.count() - 1, code, Qt.ItemDataRole.ToolTipRole)

    def _open_file(self) -> None:
        if self.item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.item.staged_path))

    def _reveal_file(self) -> None:
        if self.item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.item.staged_path).parent)))

    # --- affichage ----------------------------------------------------------------------------

    def show_item(self, item: QueueItem | None, name: str = "", folder: str = "",
                  categories: list[str] | None = None) -> None:
        """Affiche un fichier ; `name` et `folder` : valeurs en cours (éventuellement modifiées)."""
        self.item = item
        self.setVisible(item is not None)
        if item is None:
            return
        self._filling = True
        try:
            self._build_categories(categories or [])
            p = item.proposal
            ready = item.status == "ready" and p is not None
            key = item_level(item)[0]
            notes = [w for w in (p.warnings if p else []) if w.startswith(NEW_VERSION)]
            self.note.setVisible(bool(notes))
            self.note.setText(notes[0] if notes else "")
            staged, original = Path(item.staged_path), Path(item.original_path)
            self.preview.setPixmap(thumbnail(staged, 52, 52))
            self.original.setText(elided(original.name, self.original, 460, Qt.TextElideMode.ElideMiddle))
            self.original.setToolTip(original.name)
            meta = [original.suffix[1:].upper() or "Fichier"]
            if staged.exists():
                meta.append(human_size(staged.stat().st_size))
            meta.append(f"déposé depuis {original.parent.name or original.parent}")
            self.meta.setText(" · ".join(meta))
            self.meta.setToolTip(str(original.parent))
            self.name.setText(name)
            for widget in (self.name, self.browse, self.validate_button):
                widget.setEnabled(ready)
            self.set_folder(folder)
            self.pill.setText(level_text(item))
            self.bar.set_value(p.confidence if p and not p.manual else None, LEVEL_COLORS[key])
            if item.status == "analyzing":
                self.reasoning.setText("L'IA analyse ce fichier…")
            elif item.status == "error":
                self.reasoning.setText(item.error or "Erreur pendant l'analyse.")
            else:
                self.reasoning.setText(p.reasoning if p and p.reasoning else "—")
            others = [w for w in (p.warnings if p else []) if not w.startswith((HESITATION, NEW_VERSION))]
            if item.error and item.status == "ready":
                others.append(item.error)
            self.warnings.setText("\n".join(f"⚠ {w}" for w in others))
            self.warnings.setVisible(bool(others))
            self._fill_alternatives(item)
        finally:
            self._filling = False

    def _alt_row(self, index: int) -> tuple[QFrame, QLabel, QLabel]:
        row = QFrame()
        row.setObjectName("AltRow")
        row.setStyleSheet("QFrame#AltRow { border: none; border-top: 1px solid #EEF0F6; }")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 10, 0, 10)
        line.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        where = QLabel()
        where.setTextFormat(Qt.TextFormat.RichText)
        where.setWordWrap(True)
        why = muted(name="Faint")
        texts.addWidget(where)
        texts.addWidget(why)
        line.addLayout(texts, 1)
        use = QPushButton("Utiliser")
        use.setObjectName("Small")
        use.setAccessibleName(f"Utiliser la possibilité {index + 1}")
        use.clicked.connect(lambda _=False, i=index: self.alternative_chosen.emit(i))
        line.addWidget(use, 0, Qt.AlignmentFlag.AlignVCenter)
        row.hide()
        return row, where, why

    def _fill_alternatives(self, item: QueueItem) -> None:
        alternatives = item.proposal.alternatives if item.proposal else []
        self.alt_title.setVisible(bool(alternatives))
        for index, (row, where, why) in enumerate(self.alt_rows):
            if index < len(alternatives):
                alt = alternatives[index]
                parts = [html.escape(p) for p in alt.target_folder.split("/") if p]
                head = " › ".join(parts[:-1])
                where.setText(f"{head} › <b>{parts[-1]}</b>" if len(parts) > 1 else f"<b>{''.join(parts)}</b>")
                why.setText(alt.reasoning or "Autre destination plausible.")
            row.setVisible(index < len(alternatives))
