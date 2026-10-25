"""Règles apprises (Réglages › Apprentissage) : deux vues.

- Liste : trois groupes (apprises de vos corrections, confirmées par vos validations, ajoutées par vous) ; chaque
  règle est une carte dépliable qui montre sa logique, avec un interrupteur, « Modifier » et « Supprimer ».
- Texte : toutes les règles dans un grand champ, à copier, coller ou réécrire d'un coup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tribin.learning.rules_store import (
    KINDS,
    Rule,
    add_rule,
    apply_text,
    delete_rule,
    list_rules,
    refresh_confirmed_rules,
    rules_as_text,
    set_enabled,
    update_rule,
)
from tribin.ui.components import Pill, ToggleSwitch, elided, muted, section
from tribin.ui.icons import line_icon

if TYPE_CHECKING:
    from tribin.ui.app import AppController

PILLS = {"learned": ("Correction", "#FDF0D5", "#8A4B05"), "confirmed": ("Validation", "#DDF5F1", "#0F766E"),
         "manual": ("Ajoutée", "#E3E7FB", "#2F3BA0")}
EMPTY = {"learned": "Aucune pour l'instant : elles sont tirées de vos corrections (toutes les 5 corrections, ou "
                    "avec « Analyser mes corrections »).",
         "confirmed": "Aucune pour l'instant : elles apparaissent quand vous validez plusieurs fois, sans "
                      "modification, le même type de fichier vers le même dossier.",
         "manual": "Aucune : ajoutez-en avec « + Ajouter une règle »."}
STYLE = """
QFrame#RuleList { background: white; border: 1px solid #E2E5EF; border-radius: 12px; }
QFrame#RuleRow { background: transparent; border: none; border-top: 1px solid #EEF0F6; }
QFrame#RuleRow[first="true"] { border-top: none; }
QFrame#RuleRow[open="true"] { background: #F7F8FC; }
QFrame#RuleHead { background: transparent; border: none; }
QFrame#RuleHead:hover { background: #F7F8FC; }
QFrame#RuleRow QLabel { background: transparent; }
"""


class _HeadClicks(QObject):
    def __init__(self, row: RuleRow):
        super().__init__(row)
        self.row = row

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — API Qt
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.row.toggle()
            return True
        return False


class RuleRow(QFrame):
    """Une règle : en-tête (chevron, texte, sorte, interrupteur) et sa logique dépliable."""

    def __init__(self, rule: Rule, editor: RulesEditor, expanded: bool, first: bool):
        super().__init__()
        self.rule, self.editor = rule, editor
        self.setObjectName("RuleRow")
        self.setProperty("first", "true" if first else "false")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("RuleHead")
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        head.setToolTip("Cliquer pour voir la logique de cette règle")
        line = QHBoxLayout(head)
        line.setContentsMargins(12, 10, 16, 10)
        line.setSpacing(12)
        self.chevron = QLabel()
        line.addWidget(self.chevron)
        self.text = QLabel()
        self.text.setText(elided(rule.text, self.text, 470))
        self.text.setToolTip(rule.text)
        self.text.setStyleSheet("font-weight: 500;" + ("" if rule.enabled else " color: #8A8FAE;"))
        line.addWidget(self.text, 1)
        label, background, color = PILLS.get(rule.kind, PILLS["manual"])
        line.addWidget(Pill(label, (background, color)))
        self.switch = ToggleSwitch(rule.enabled)
        self.switch.setToolTip("Règle active : donnée à l'IA à chaque proposition")
        self.switch.toggled.connect(lambda on: editor.set_enabled(rule, on))
        line.addWidget(self.switch)
        outer.addWidget(head)
        head.installEventFilter(_HeadClicks(self))

        self.details = QWidget()
        box = QVBoxLayout(self.details)
        box.setContentsMargins(40, 2, 16, 14)
        box.setSpacing(6)
        full = QLabel(rule.text)
        full.setWordWrap(True)
        full.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(full)
        box.addSpacing(4)
        box.addWidget(section("Logique"))
        for text in self._logic():
            item = muted(text)
            item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(item)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        edit = QPushButton("Modifier")
        edit.setObjectName("Small")
        edit.setIcon(line_icon("edit", "#1F2544", 14))
        edit.clicked.connect(lambda: editor.edit_rule(rule))
        remove = QPushButton("Supprimer")
        remove.setObjectName("Small")
        remove.clicked.connect(lambda: editor.delete_rule(rule))
        actions.addWidget(edit)
        actions.addWidget(remove)
        actions.addStretch()
        box.addSpacing(6)
        box.addLayout(actions)
        outer.addWidget(self.details)
        self.set_expanded(expanded)

    def _logic(self) -> list[str]:
        d, created = self.rule.details, self.rule.created_at[:10]
        if self.rule.kind == "confirmed":
            lines = [f"Vous avez validé {d.get('count', '?')} fois, sans rien modifier, un fichier de ce type vers "
                     f"« {d.get('folder', '?')} » : TriBin en fait une règle."]
            lines += [f"• {e}" for e in d.get("examples", [])[:6]]
        elif self.rule.kind == "learned":
            lines = [f"Tirée de vos corrections ({d.get('count', '?')} au moment de l'analyse) : là où vous avez "
                     "changé le dossier ou le nom proposé par l'IA."]
            lines += [f"• {e.lstrip('- ')}" for e in d.get("corrections", [])[:6]]
        else:
            lines = ["Ajoutée par vous : l'IA la suit telle quelle."]
        lines.append(f"Créée le {created}." if created else "")
        lines.append("Active : donnée à l'IA à chaque proposition." if self.rule.enabled
                     else "Désactivée : l'IA ne la voit pas.")
        return [line for line in lines if line]

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.details.setVisible(expanded)
        self.chevron.setPixmap(line_icon("chevron-down" if expanded else "chevron-right", "#5B6080", 16).pixmap(16, 16))
        self.setProperty("open", "true" if expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def toggle(self) -> None:
        self.set_expanded(not self.expanded)
        (self.editor.expanded.add if self.expanded else self.editor.expanded.discard)(self.rule.id)


class RulesEditor(QWidget):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.db = controller.service.db
        self.expanded: set[int] = set()
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.views = QButtonGroup(self)
        for index, label in enumerate(("Liste", "Texte")):
            button = QPushButton(label)
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.views.addButton(button, index)
            bar.addWidget(button)
        self.views.idClicked.connect(self.show_view)
        bar.addStretch()
        analyze = QPushButton("Analyser mes corrections")
        analyze.setObjectName("Small")
        analyze.setIcon(line_icon("sparkle", "#1F2544", 14))
        analyze.setToolTip("Demander à l'IA de tirer des règles de vos corrections, maintenant")
        analyze.clicked.connect(self.analyze)
        add = QPushButton("Ajouter une règle")
        add.setObjectName("Primary")
        add.setIcon(line_icon("edit", "#FFFFFF", 14))
        add.clicked.connect(self.add_rule)
        bar.addWidget(analyze)
        bar.addWidget(add)
        layout.addLayout(bar)

        self.stack = QStackedWidget()
        self.list_page = QWidget()
        self.groups = QVBoxLayout(self.list_page)
        self.groups.setContentsMargins(0, 0, 0, 0)
        self.groups.setSpacing(8)
        self.stack.addWidget(self.list_page)
        text_page = QWidget()
        text_box = QVBoxLayout(text_page)
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(8)
        text_box.addWidget(muted("Une règle par ligne. « # » au début : règle désactivée. Les étiquettes [apprise], "
                                 "[confirmée] et [ajoutée] sont facultatives ; une nouvelle ligne devient une règle "
                                 "ajoutée par vous, une ligne effacée est supprimée."))
        self.text = QPlainTextEdit()
        self.text.setMinimumHeight(260)
        text_box.addWidget(self.text)
        apply_row = QHBoxLayout()
        copy = QPushButton("Copier tout")
        copy.setObjectName("Small")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        apply = QPushButton("Appliquer le texte")
        apply.setObjectName("Primary")
        apply.clicked.connect(self.apply_text)
        apply_row.addWidget(copy)
        apply_row.addStretch()
        apply_row.addWidget(apply)
        text_box.addLayout(apply_row)
        self.stack.addWidget(text_page)
        layout.addWidget(self.stack)

        try:
            refresh_confirmed_rules(self.db)
        except Exception:  # signal facultatif
            pass
        self.reload()

    # --- affichage ----------------------------------------------------------------------------

    def show_view(self, index: int) -> None:
        if index == 1:
            self.text.setPlainText(rules_as_text(self.db))
        else:
            self.reload()
        self.views.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)

    def reload(self) -> None:
        while self.groups.count():
            widget = self.groups.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        rules = list_rules(self.db)
        for kind in ("learned", "confirmed", "manual"):
            members = [r for r in rules if r.kind == kind]
            title = {"learned": "Apprises de vos corrections", "confirmed": "Confirmées par vos validations",
                     "manual": "Ajoutées par vous"}[kind]
            header = section(f"{title} · {len(members)}")
            self.groups.addWidget(header)
            if not members:
                empty = muted(EMPTY[kind])
                empty.setContentsMargins(0, 0, 0, 8)
                self.groups.addWidget(empty)
                continue
            card = QFrame()
            card.setObjectName("RuleList")
            rows = QVBoxLayout(card)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(0)
            for index, rule in enumerate(members):
                rows.addWidget(RuleRow(rule, self, rule.id in self.expanded, index == 0))
            self.groups.addWidget(card)
        for index in range(self.groups.count()):
            widget = self.groups.itemAt(index).widget()
            if widget:
                widget.show()

    # --- actions ------------------------------------------------------------------------------

    def set_enabled(self, rule: Rule, enabled: bool) -> None:
        set_enabled(self.db, rule.id, enabled)

    def add_rule(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Ajouter une règle",
                                                 "Une consigne pour l'IA, en une phrase. Exemple :\n« Les factures "
                                                 "d'électricité vont dans Logement/Energie. »")
        if ok and text.strip():
            add_rule(self.db, " ".join(text.split()), "manual")
            self.show_view(0)

    def edit_rule(self, rule: Rule) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Modifier la règle", "Règle :", rule.text)
        if ok and text.strip():
            update_rule(self.db, rule.id, " ".join(text.split()))
            self.reload()

    def delete_rule(self, rule: Rule) -> None:
        if QMessageBox.question(self, "Supprimer la règle ?", rule.text) == QMessageBox.StandardButton.Yes:
            delete_rule(self.db, rule.id)
            self.expanded.discard(rule.id)
            self.reload()

    def apply_text(self) -> None:
        apply_text(self.db, self.text.toPlainText())
        self.show_view(0)

    def analyze(self) -> None:
        from tribin.learning.corrections import LEARNABLE, list_corrections
        from tribin.learning.signals import maybe_summarize

        if not [c for c in list_corrections(self.db) if c.decision in LEARNABLE]:
            QMessageBox.information(self, "TriBin", "Pas encore de corrections à analyser : elles viennent des "
                                    "fichiers dont vous avez changé le dossier ou le nom.")
            return
        llm = self.c.llm_or_none()
        if llm is None:
            QMessageBox.information(self, "TriBin", "Configurez l'IA (Réglages › Intelligence artificielle) pour "
                                    "analyser vos corrections.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            changed = maybe_summarize(self.db, llm, force=True)
        finally:
            QApplication.restoreOverrideCursor()
        self.show_view(0)
        if not changed:
            QMessageBox.information(self, "TriBin", "L'analyse n'a pas abouti ; réessayez plus tard.")


__all__ = ["KINDS", "RulesEditor"]
