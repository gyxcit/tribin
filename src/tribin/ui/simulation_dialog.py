"""Simulation d'un lot : ce qui va être rangé, créé ou mis de côté, avant de toucher au moindre fichier."""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tribin.safety.executor import SimulationReport
from tribin.safety.operations import Operation
from tribin.ui.components import Pill
from tribin.ui.theme import BORDER, mono_font

# libellé du badge, couleurs (fond, texte), type de ligne (style)
BADGES = {"move": ("RANGER", ("#14B8A6", "#FFFFFF"), "move"), "archive": ("METTRE DE CÔTÉ", ("#F5A524", "#1F2544"), "archive"),
          "mkdir": ("NOUVEAU DOSSIER", ("#E8EAF6", "#2C3460"), "mkdir"), "problem": ("PROBLÈME", ("#F0605A", "#FFFFFF"), "problem")}


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:
        return str(path)


class SimulationDialog(QDialog):
    """Montre la simulation d'un lot ; exec() renvoie Accepted si l'utilisateur lance le rangement."""

    def __init__(self, report: SimulationReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TriBin — Simulation")
        self.resize(860, 640)
        ops = report.operations
        problems = {op.operation_id: report.problems.get(op.operation_id, []) for op in ops}
        files = [op for op in ops if op.action == "move" and not op.meta.get("version_archive")]
        archives = [op for op in ops if op.action == "move" and op.meta.get("version_archive")]
        mkdirs = [op for op in ops if op.action == "mkdir"]
        problem_count = sum(1 for p in problems.values() if p)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QFrame()
        head.setObjectName("SimHead")
        head.setStyleSheet(f"QFrame#SimHead {{ background: white; border: none; border-bottom: 1px solid {BORDER}; }}")
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(28, 22, 28, 16)
        head_layout.setSpacing(10)
        title = QLabel(f"Simulation : {_plural(len(files), 'fichier')} à ranger")
        title.setObjectName("Title")
        subtitle = QLabel("Rien n'a encore été déplacé. Vérifie, puis lance le rangement." if not problem_count else
                          "Un problème empêche ce rangement : rien ne sera déplacé tant qu'il n'est pas réglé.")
        subtitle.setObjectName("Muted")
        head_layout.addWidget(title)
        head_layout.addWidget(subtitle)
        pills = QHBoxLayout()
        pills.setSpacing(8)
        pills.addWidget(Pill(_plural(len(files), "rangement"), ("#DDF5F1", "#0F766E")))
        if mkdirs:
            pills.addWidget(Pill(_plural(len(mkdirs), "dossier créé", "dossiers créés"), ("#E8EAF6", "#2C3460")))
        if archives:
            pills.addWidget(Pill(_plural(len(archives), "ancienne version mise de côté", "anciennes versions mises de côté"),
                                 ("#FDF0D5", "#8A4B05")))
        pills.addWidget(Pill(_plural(problem_count, "problème"),
                             ("#FDE4E2", "#A42A25") if problem_count else ("#F5F6FA", "#5B6080")))
        pills.addStretch()
        head_layout.addLayout(pills)
        layout.addWidget(head)

        tree = QWidget()
        tree_layout = QVBoxLayout(tree)
        tree_layout.setContentsMargins(28, 18, 28, 18)
        tree_layout.setSpacing(14)
        for folder, members in self._groups(ops).items():
            tree_layout.addWidget(self._folder_title(folder))
            box = QFrame()
            box.setStyleSheet(f"QFrame#Branch {{ border: none; border-left: 2px solid {BORDER}; }}")
            box.setObjectName("Branch")
            branch = QVBoxLayout(box)
            branch.setContentsMargins(14, 0, 0, 0)
            branch.setSpacing(8)
            for op in members:
                branch.addWidget(self._op_row(op, problems[op.operation_id]))
            wrap = QHBoxLayout()
            wrap.setContentsMargins(14, 0, 0, 0)
            wrap.addWidget(box)
            tree_layout.addLayout(wrap)
        tree_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(tree)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        foot = QFrame()
        foot.setObjectName("SimFoot")
        foot.setStyleSheet(f"QFrame#SimFoot {{ background: #FAFBFE; border: none; border-top: 1px solid {BORDER}; }}")
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(28, 14, 28, 18)
        note = QLabel("↺  Tout sera annulable d'un clic depuis l'Historique.")
        note.setObjectName("Muted")
        foot_layout.addWidget(note, 1)
        back = QPushButton("Retour")
        back.clicked.connect(self.reject)
        self.confirm = QPushButton(f"Ranger {_plural(len(files), 'fichier')}" if len(files) != 1 else "Ranger le fichier")
        self.confirm.setObjectName("Primary")
        self.confirm.setEnabled(not problem_count)
        self.confirm.clicked.connect(self.accept)
        self.confirm.setDefault(True)
        foot_layout.addWidget(back)
        foot_layout.addWidget(self.confirm)
        layout.addWidget(foot)

    @staticmethod
    def _groups(ops: list[Operation]) -> OrderedDict[str, list[Operation]]:
        """Opérations regroupées par dossier de destination (relatif à la racine)."""
        groups: OrderedDict[str, list[Operation]] = OrderedDict()
        for op in ops:
            folder = _relative(op.destination.parent, op.root)
            groups.setdefault(folder, []).append(op)
        return groups

    @staticmethod
    def _folder_title(folder: str) -> QLabel:
        parts = [p for p in folder.split("/") if p and p != "."]
        label = QLabel(" › ".join(parts) if parts else "(racine)")
        label.setStyleSheet("font-weight: 700;")
        return label

    @staticmethod
    def _op_row(op: Operation, problems: list[str]) -> QFrame:
        key = "problem" if problems else "mkdir" if op.action == "mkdir" else \
            "archive" if op.meta.get("version_archive") else "move"
        text, colors, kind = BADGES[key]
        row = QFrame()
        row.setObjectName("OpRow")
        row.setProperty("kind", kind)
        line = QHBoxLayout(row)
        line.setContentsMargins(12, 9, 12, 9)
        line.setSpacing(10)
        badge = Pill(text, colors)
        badge.setStyleSheet(badge.styleSheet().replace("border-radius: 11px", "border-radius: 6px") + " font-size: 10px;")
        line.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        name = QLabel(op.destination.name)
        name.setFont(mono_font())
        name.setWordWrap(True)
        texts.addWidget(name)
        for problem in problems:  # d'abord ce qui bloque, en clair
            blocking = QLabel(problem)
            blocking.setWordWrap(True)
            blocking.setStyleSheet("color: #A42A25; font-weight: 600;")
            texts.addWidget(blocking)
        details = []
        if op.source and op.action != "mkdir":
            details.append("ancienne version" if op.meta.get("version_archive") else f"depuis « {op.source.name} »")
        if not problems:  # un fichier introuvable ne sera pas renommé : la remarque sur le nom ne ferait qu'embrouiller
            details += op.notes
        if details:
            info = QLabel(" · ".join(details))
            info.setObjectName("Muted")
            info.setWordWrap(True)
            texts.addWidget(info)
        line.addLayout(texts, 1)
        return row
