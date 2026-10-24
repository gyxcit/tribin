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


class FolderPicker(QWidget):
    """Liste de dossiers choisis un par un, chacun retirable."""

    changed = Signal()

    def __init__(self, values: list[str], add_label: str = "Ajouter un dossier",
                 more_label: str = "Ajouter un autre dossier", dialog_title: str = "Choisir un dossier",
                 empty_text: str = "", to_value: Callable[[Path], str | None] | None = None,
                 to_label: Callable[[str], str] | None = None, start_dir: Callable[[], str] | None = None):
        super().__init__()
        self.values_: list[str] = []
        self.add_label, self.more_label, self.dialog_title = add_label, more_label, dialog_title
        self.to_value = to_value or (lambda path: str(path))
        self.to_label = to_label or (lambda value: value)
        self.start_dir = start_dir or (lambda: "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        layout.addLayout(self.rows)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        self.empty.setVisible(bool(empty_text))
        layout.addWidget(self.empty)
        self.add_button = QPushButton()
        self.add_button.setObjectName("Link")
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
        row.setStyleSheet("QFrame#FolderRow { background: white; border: 1px solid #E2E5EF; border-radius: 8px; }"
                          "QFrame#FolderRow QLabel { background: transparent; }")
        line = QHBoxLayout(row)
        line.setContentsMargins(10, 6, 6, 6)
        icon = QLabel()
        icon.setPixmap(QFileIconProvider().icon(QFileIconProvider.IconType.Folder).pixmap(18, 18))
        label = QLabel()
        text = self.to_label(value)
        label.setText(elided(text, label, 440, Qt.TextElideMode.ElideMiddle))
        label.setToolTip(text)
        remove = QPushButton("Retirer")
        remove.setObjectName("Link")
        remove.setAccessibleName(f"Retirer {text}")
        remove.clicked.connect(lambda _=False, v=value, r=row: self._remove(v, r))
        line.addWidget(icon)
        line.addWidget(label, 1)
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
        self.empty.setVisible(not has and bool(self.empty.text()))


# --- dossiers à ranger / à exclure ----------------------------------------------------------------


def roots_picker(values: list[str]) -> FolderPicker:
    return FolderPicker(values, "Ajouter un dossier à ranger", "Ajouter un autre dossier",
                        "Choisir un dossier à ranger", "Aucun dossier choisi pour l'instant.")


def excluded_label(pattern: str) -> str:
    """Motif glob affiché simplement : « ACME/2026/_PROJET/** » -> « ACME/2026/_PROJET »."""
    generic = GENERIC.match(pattern)
    if generic:
        return f"Tous les dossiers nommés « {generic.group(1)} »"
    return pattern.removesuffix("/**")


def excluded_value(path: Path, roots: list[str]) -> str:
    """Motif relatif à la racine qui contient le dossier ; erreur claire s'il n'est dans aucune."""
    for root in roots:
        if is_within(path, Path(root)):
            rel = Path(os.path.relpath(path.resolve(), Path(root).resolve())).as_posix()
            if rel in {".", ""}:
                raise ValueError("Ce dossier est un dossier à ranger : retire-le de la liste plutôt que de l'exclure.")
            return f"{rel}/**"
    raise ValueError("Choisis un dossier situé à l'intérieur d'un des dossiers à ranger.")


def excluded_picker(values: list[str], roots: Callable[[], list[str]]) -> FolderPicker:
    return FolderPicker(values, "Ajouter un dossier à exclure", "Ajouter un autre dossier à exclure",
                        "Choisir un dossier auquel TriBin ne touchera jamais",
                        "Aucun : TriBin peut ranger partout dans tes dossiers.",
                        to_value=lambda path: excluded_value(path, roots()), to_label=excluded_label,
                        start_dir=lambda: (roots() or [""])[0])
