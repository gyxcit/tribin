"""Sélection de dossiers un par un : « + Ajouter un dossier », puis « + Ajouter un autre dossier ».

Sert aux dossiers à ranger (chemins complets) et aux dossiers à exclure (motifs relatifs à un dossier à ranger).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tribin.config import is_within
from tribin.ui.components import elided

GENERIC = re.compile(r"^\*\*/([^/*?]+)/\*\*$")
TEXT_WIDTH = 320


def root_description(value: str) -> tuple[str, str]:
    """Dossier à ranger : son nom, puis son chemin complet."""
    path = Path(value)
    return path.name or str(path), str(path)


class FolderPicker(QWidget):
    """Liste de dossiers choisis un par un, chacun retirable."""

    changed = Signal()

    def __init__(self, values: list[str], add_label: str = "Ajouter un dossier",
                 more_label: str = "Ajouter un autre dossier", dialog_title: str = "Choisir un dossier",
                 empty_text: str = "", to_value: Callable[[Path], str | None] | None = None,
                 describe: Callable[[str], tuple[str, str]] | None = None, start_dir: Callable[[], str] | None = None):
        super().__init__()
        self.values_: list[str] = []
        self.add_label, self.more_label, self.dialog_title = add_label, more_label, dialog_title
        self.to_value = to_value or (lambda path: str(path))
        self.describe = describe or root_description
        self.start_dir = start_dir or (lambda: "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        layout.addLayout(self.rows)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("EmptyBox")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.add_button = QPushButton()
        self.add_button.clicked.connect(self.pick)
        layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        for value in values:
            self._add_row(value)
        self._refresh()

    # --- valeurs ------------------------------------------------------------------------------

    def values(self) -> list[str]:
        return list(self.values_)

    def add_value(self, value: str) -> None:
        if value and value not in self.values_:
            self._add_row(value)
            self._refresh()
            self.changed.emit()

    def set_values(self, values: list[str]) -> None:
        """Remplace toute la liste (ex. changement de mode Particulier / Professionnel dans les réglages)."""
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self.values_ = []
        for value in values:
            self._add_row(value)
        self._refresh()

    def pick(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.dialog_title, self.start_dir())
        if not chosen:
            return
        try:
            value = self.to_value(Path(chosen))
        except ValueError as exc:
            QMessageBox.information(self, "TriBin", str(exc))
            return
        if value:
            self.add_value(value)

    # --- lignes -------------------------------------------------------------------------------

    def _add_row(self, value: str) -> None:
        self.values_.append(value)
        row = QFrame()
        row.setObjectName("FolderRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(12, 8, 8, 8)
        line.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(QFileIconProvider().icon(QFileIconProvider.IconType.Folder).pixmap(20, 20))
        texts = QVBoxLayout()
        texts.setSpacing(0)
        title, subtitle = self.describe(value)
        name = QLabel()
        name.setStyleSheet("font-weight: 500;")
        name.setText(elided(title, name, TEXT_WIDTH, Qt.TextElideMode.ElideMiddle))
        where = QLabel()
        where.setObjectName("Faint")
        where.setText(elided(subtitle, where, TEXT_WIDTH, Qt.TextElideMode.ElideMiddle))
        row.setToolTip(subtitle)
        texts.addWidget(name)
        texts.addWidget(where)
        remove = QPushButton("Retirer")
        remove.setObjectName("Ghost")
        remove.setAccessibleName(f"Retirer {title}")
        remove.clicked.connect(lambda _=False, v=value, r=row: self._remove(v, r))
        line.addWidget(icon)
        line.addLayout(texts, 1)
        line.addWidget(remove)
        self.rows.addWidget(row)
        row.show()

    def _remove(self, value: str, row: QFrame) -> None:
        if value in self.values_:
            self.values_.remove(value)
        row.hide()
        row.deleteLater()
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        has = bool(self.values_)
        self.add_button.setText(f"+  {self.more_label if has else self.add_label}")
        self.add_button.setObjectName("Link" if has else "")  # bouton bien visible tant que la liste est vide
        self.add_button.style().unpolish(self.add_button)
        self.add_button.style().polish(self.add_button)
        self.empty.setVisible(not has and bool(self.empty.text()))


# --- dossiers à ranger / à exclure ----------------------------------------------------------------


def roots_picker(values: list[str]) -> FolderPicker:
    return FolderPicker(values, "Ajouter un dossier", "Ajouter un autre dossier",
                        "Choisir un dossier à ranger", "Aucun dossier choisi pour l'instant.")


def excluded_label(pattern: str) -> str:
    """Motif glob affiché simplement : « ACME/2026/_PROJET/** » -> « ACME/2026/_PROJET »."""
    generic = GENERIC.match(pattern)
    if generic:
        return f"Tous les dossiers nommés « {generic.group(1)} »"
    return pattern[:-3] if pattern.endswith("/**") else pattern


def excluded_description(pattern: str) -> tuple[str, str]:
    """Dossier exclu : son nom, puis où il se trouve (« ACME › 2026 ») ou « tous les dossiers de ce nom »."""
    generic = GENERIC.match(pattern)
    if generic:
        return generic.group(1), "Tous les dossiers portant ce nom"
    parts = [p for p in excluded_label(pattern).split("/") if p]
    return (parts[-1] if parts else pattern), (" › ".join(parts[:-1]) or "À la racine du dossier à ranger")


def excluded_value(path: Path, roots: list[str]) -> str:
    """Motif relatif à la racine qui contient le dossier ; erreur claire s'il n'est dans aucune."""
    for root in roots:
        if is_within(path, Path(root)):
            rel = Path(os.path.relpath(path.resolve(), Path(root).resolve())).as_posix()
            if rel in {".", ""}:
                raise ValueError("Ce dossier est un dossier à ranger : retirez-le de la liste plutôt que de l'exclure.")
            return f"{rel}/**"
    raise ValueError("Choisissez un dossier situé à l'intérieur d'un des dossiers à ranger.")


def excluded_picker(values: list[str], roots: Callable[[], list[str]]) -> FolderPicker:
    return FolderPicker(values, "Ajouter un dossier à exclure", "Ajouter un autre dossier à exclure",
                        "Choisir un dossier auquel TriBin ne touchera jamais",
                        "Aucun pour l'instant : TriBin peut ranger partout dans vos dossiers.",
                        to_value=lambda path: excluded_value(path, roots()), describe=excluded_description,
                        start_dir=lambda: (roots() or [""])[0])
