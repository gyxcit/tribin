"""Panneau de détail de la Corbeille : avant → après, destination, catégorie en un clic, confiance, actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tribin.service.queue import QueueItem
from tribin.ui.components import Breadcrumb, ConfidenceGauge, KeyButton, Pill, elided, item_level, section, thumbnail
from tribin.ui.theme import BORDER, mono_font

HESITATION = "L'IA hésite avec"
NEW_VERSION = "Nouvelle version"


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
        self.setObjectName("Card")
        self.item: QueueItem | None = None
        self._folder = ""
        self._categories: list[str] = []
        self._filling = False

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 22, 24, 12)
        body.setSpacing(18)

        top = QHBoxLayout()
        top.setSpacing(24)
        self.preview = QLabel()
        self.preview.setFixedSize(150, 190)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #F5F6FA; border-radius: 10px;")
        top.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(8)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.pill = Pill()
        self.note = Pill(colors=("#E8EAF6", "#2C3460"))
        chips.addWidget(self.pill)
        chips.addWidget(self.note)
        chips.addStretch()
        names.addLayout(chips)
        names.addWidget(section("Avant"))
        self.original = QLabel()
        strike = mono_font()
        strike.setStrikeOut(True)
        self.original.setFont(strike)
        self.original.setObjectName("Strike")
        self.original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        names.addWidget(self.original)
        names.addWidget(section("Après"))
        name_row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setObjectName("NewName")
        self.name.setFont(mono_font())
        self.name.setAccessibleName("Nouveau nom")
        self.name.textChanged.connect(self._changed)
        self.name.returnPressed.connect(self.validate_clicked)
        self.rename_button = KeyButton("Modifier", "E")
        self.rename_button.clicked.connect(self.focus_name)
        name_row.addWidget(self.name, 1)
        name_row.addWidget(self.rename_button)
        names.addLayout(name_row)
        names.addStretch()
        top.addLayout(names, 1)
        body.addLayout(top)

        destination = QVBoxLayout()
        destination.setSpacing(10)
        destination.addWidget(section("Destination"))
        crumb_row = QHBoxLayout()
        self.breadcrumb = Breadcrumb()
        self.browse = QPushButton("Autre dossier…")
        self.browse.setObjectName("Link")
        self.browse.clicked.connect(self.browse_clicked)
        crumb_row.addWidget(self.breadcrumb)
        crumb_row.addWidget(self.browse)
        crumb_row.addStretch()
        destination.addLayout(crumb_row)
        self.cat_row = QHBoxLayout()
        self.cat_row.setSpacing(6)
        self.cat_group = QButtonGroup(self)
        self.cat_group.setExclusive(True)
        self.cat_group.buttonClicked.connect(self._category_clicked)
        destination.addLayout(self.cat_row)
        body.addLayout(destination)

        confidence = QVBoxLayout()
        confidence.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(section("Confiance de l'IA"))
        head.addStretch()
        self.conf_value = QLabel()
        self.conf_value.setStyleSheet("font-weight: 700;")
        head.addWidget(self.conf_value)
        confidence.addLayout(head)
        self.gauge = ConfidenceGauge()
        confidence.addWidget(self.gauge)
        legend = QHBoxLayout()
        for text in ("À vérifier", "À regarder", "Sûr"):
            label = QLabel(text)
            label.setObjectName("Muted")
            legend.addWidget(label)
            if text != "Sûr":
                legend.addStretch()
        confidence.addLayout(legend)
        body.addLayout(confidence)

        body.addWidget(section("Pourquoi cette proposition"))
        self.reasoning = QLabel()
        self.reasoning.setWordWrap(True)
        self.reasoning.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.reasoning)
        self.warnings = QLabel()
        self.warnings.setObjectName("Warning")
        self.warnings.setWordWrap(True)
        body.addWidget(self.warnings)

        self.alt_title = section("L'IA hésite avec")
        self.alt_title.setStyleSheet("color: #8A4B05;")
        body.addWidget(self.alt_title)
        self.alt_box = QVBoxLayout()
        self.alt_box.setSpacing(8)
        self.alt_cards = [self._alt_card(index) for index in range(2)]  # créés une fois, réutilisés
        for card, _, _ in self.alt_cards:
            self.alt_box.addWidget(card)
        body.addLayout(self.alt_box)
        body.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        actions = QFrame()
        actions.setObjectName("ActionBar")
        actions.setStyleSheet(f"QFrame#ActionBar {{ border: none; border-top: 1px solid {BORDER}; background: transparent; }}")
        bar = QHBoxLayout(actions)
        bar.setContentsMargins(24, 14, 24, 18)
        self.validate_button = KeyButton("Valider et ranger", "Entrée", "Primary")
        self.validate_button.clicked.connect(self.validate_clicked)
        self.return_button = KeyButton("Renvoyer à l'origine", "R")
        self.return_button.clicked.connect(self.return_clicked)
        self.skip_button = KeyButton("Passer", "Échap", "Ghost")
        self.skip_button.clicked.connect(self.skip_clicked)
        bar.addWidget(self.validate_button)
        bar.addWidget(self.return_button)
        bar.addStretch()
        bar.addWidget(self.skip_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
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
        for button in self.cat_group.buttons():
            button.setChecked(button.property("code") == current)
            button.setEnabled(bool(parts) and current in self._categories and self.name.isEnabled())
        self._changed()

    def focus_name(self) -> None:
        self.name.setFocus()
        self.name.selectAll()

    def _changed(self) -> None:
        if not self._filling:
            self.edited.emit()

    def _category_clicked(self, button: QPushButton) -> None:
        parts = [p for p in self._folder.split("/") if p]
        if parts and parts[-1] in self._categories:
            parts[-1] = button.property("code")
            self.set_folder("/".join(parts))

    def _build_categories(self, categories: list[str]) -> None:
        if categories == self._categories:
            return
        self._categories = categories
        for button in self.cat_group.buttons():
            self.cat_group.removeButton(button)
            button.hide()
            button.deleteLater()
        while self.cat_row.count():
            self.cat_row.takeAt(0)
        for code in categories:
            button = QPushButton(category_label(code))
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setProperty("code", code)
            button.setToolTip(code)
            self.cat_group.addButton(button)
            self.cat_row.addWidget(button)
            button.show()
        self.cat_row.addStretch()

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
            _, _, background, text = item_level(item)
            self.pill.setText(level_text(item))
            self.pill.set_colors((background, text))
            notes = [w for w in (p.warnings if p else []) if w.startswith(NEW_VERSION)]
            self.note.setVisible(bool(notes))
            self.note.setText(notes[0] if notes else "")
            self.preview.setPixmap(thumbnail(Path(item.staged_path), 140, 180))
            original = Path(item.original_path).name
            self.original.setText(elided(original, self.original, 520, Qt.TextElideMode.ElideMiddle))
            self.original.setToolTip(f"{original}\nVenait de : {Path(item.original_path).parent}")
            self.name.setText(name)
            for widget in (self.name, self.rename_button, self.browse, self.validate_button):
                widget.setEnabled(ready)
            self.set_folder(folder)
            self.conf_value.setText(f"{p.confidence:.0%}".replace("%", " %") if p and not p.manual else "—")
            self.conf_value.setStyleSheet(f"font-weight: 700; color: {text};")
            self.gauge.set_value(p.confidence if p and not p.manual else None)
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

    def _alt_card(self, index: int) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("AltCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 10, 10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        where = QLabel()
        bold = QFont(where.font())
        bold.setBold(True)
        where.setFont(bold)
        where.setWordWrap(True)
        why = QLabel()
        why.setStyleSheet("color: #6B5A3A;")
        why.setWordWrap(True)
        texts.addWidget(where)
        texts.addWidget(why)
        row.addLayout(texts, 1)
        use = QPushButton("Utiliser cette piste")
        use.setObjectName("AltButton")
        use.clicked.connect(lambda _=False, i=index: self.alternative_chosen.emit(i))
        row.addWidget(use, 0, Qt.AlignmentFlag.AlignVCenter)
        card.hide()
        return card, where, why

    def _fill_alternatives(self, item: QueueItem) -> None:
        alternatives = item.proposal.alternatives if item.proposal else []
        self.alt_title.setVisible(bool(alternatives))
        for index, (card, where, why) in enumerate(self.alt_cards):
            if index < len(alternatives):
                alt = alternatives[index]
                where.setText(" › ".join(p for p in alt.target_folder.split("/") if p))
                why.setText(alt.reasoning or "Autre destination plausible.")
            card.setVisible(index < len(alternatives))
