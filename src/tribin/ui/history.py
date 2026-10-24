"""Historique : opérations du journal regroupées par jour et par lot, annulables par opération ou par lot."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tribin.config import STAGING_DIRNAME
from tribin.safety.journal import Journal
from tribin.ui.components import elided, section
from tribin.ui.theme import BORDER, CORAL, FAINT, TEAL, mono_font

if TYPE_CHECKING:
    from tribin.ui.app import AppController

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
REVERSIBLE = {"stage", "move", "rename", "archive", "mkdir"}
VISIBLE_ROWS = 4
MAX_BATCHES = 80

# libellé, couleur du libellé
KINDS = {"moved": ("RANGÉ", "#0F766E"), "edited": ("MODIFIÉ", "#2C3460"), "archived": ("MIS DE CÔTÉ", "#8A4B05"),
         "staged": ("DÉPOSÉ", "#5B6080"), "mkdir": ("DOSSIER CRÉÉ", "#5B6080"), "undone": ("ANNULÉ", "#5B6080"),
         "failed": ("ÉCHEC", "#A42A25"), "other": ("OPÉRATION", "#5B6080")}


def day_label(day: str) -> str:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    today = date.today()
    if d == today:
        return "Aujourd'hui"
    if d == today - timedelta(days=1):
        return "Hier"
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def op_kind(op: dict) -> str:
    if op.get("status") == "undone":
        return "undone"
    if op.get("status") in {"failed", "skipped"}:
        return "failed"
    action = op.get("action")
    if action == "move":
        if op.get("version_archive"):
            return "archived"
        return "edited" if op.get("decision") in {"edited", "alternative_chosen"} else "moved"
    return {"stage": "staged", "mkdir": "mkdir", "archive": "archived"}.get(action, "other")


def relative(path: str | None, root: str | None) -> str:
    if path and root:
        try:
            return Path(path).relative_to(Path(root)).as_posix()
        except ValueError:
            pass
    return path or ""


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


class HistoryView(QWidget):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.expanded: set[str] = set()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        wrapper = QHBoxLayout(page)
        wrapper.setContentsMargins(24, 24, 24, 24)
        column_box = QWidget()
        column_box.setMaximumWidth(1080)
        wrapper.addStretch()
        wrapper.addWidget(column_box, 100)
        wrapper.addStretch()
        self.column = QVBoxLayout(column_box)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Historique")
        title.setObjectName("Title")
        subtitle = QLabel("Chaque rangement est noté avant d'être fait. Un lot entier s'annule d'un clic, sans rien écraser.")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        self.filters = QButtonGroup(self)
        for key, label in (("all", "Tout"), ("moves", "Rangements"), ("undone", "Annulations")):
            button = QPushButton(label)
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setProperty("key", key)
            button.setChecked(key == "all")
            self.filters.addButton(button)
            head.addWidget(button, 0, Qt.AlignmentFlag.AlignBottom)
        self.filters.buttonClicked.connect(lambda _: self.reload())
        self.period = QComboBox()
        self.period.addItem("7 derniers jours", 7)
        self.period.addItem("30 derniers jours", 30)
        self.period.addItem("Tout", 0)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(lambda _: self.reload())
        head.addWidget(self.period, 0, Qt.AlignmentFlag.AlignBottom)
        self.column.addLayout(head)
        self.content = QVBoxLayout()
        self.content.setSpacing(14)
        self.column.addLayout(self.content)
        self.footer = QLabel()
        self.footer.setObjectName("Muted")
        self.footer.setWordWrap(True)
        self.column.addWidget(self.footer)
        self.column.addStretch()

    # --- données ------------------------------------------------------------------------------

    def _batches(self, journal: Journal) -> list[tuple[str, list[str], list[dict]]]:
        """[(jour, lot, opérations)] du plus récent au plus ancien, selon les filtres."""
        days = self.period.currentData()
        since = (date.today() - timedelta(days=days)).isoformat() if days else ""
        ops = [o for o in journal.operations() if o.get("action") != "undo" and o.get("ts", "")[:10] >= since]
        batches: dict[str, list[dict]] = {}
        for op in ops:
            batches.setdefault(op.get("batch_id") or op["operation_id"], []).append(op)
        key = self.filters.checkedButton().property("key")
        result = []
        for batch_id, members in batches.items():
            if key == "moves" and not any(o.get("action") == "move" for o in members):
                continue
            if key == "undone" and not any(o.get("status") == "undone" for o in members):
                continue
            members.sort(key=lambda o: o.get("ts", ""))
            day = members[0].get("ts", "")[:10]
            deposit = all(o.get("action") in {"stage", "mkdir"} for o in members)
            previous = result[-1] if result else None
            if deposit and previous and previous[0] == day and previous[3]:
                # dépôts successifs du même jour : une seule carte (un fichier déposé = un lot)
                previous[1].append(batch_id)
                previous[2][:0] = members
                continue
            result.append((day, [batch_id], members, deposit))
        return [(day, ids, members) for day, ids, members, _ in result[:MAX_BATCHES]]

    # --- affichage ----------------------------------------------------------------------------

    def reload(self) -> None:
        while self.content.count():
            widget = self.content.takeAt(0).widget()
            if widget:
                widget.hide()  # sinon visible jusqu'à sa destruction effective
                widget.deleteLater()
        journal = Journal(self.c.service.settings.journal_dir)
        batches = self._batches(journal)
        if not batches:
            empty = QLabel("Aucune opération sur cette période.")
            empty.setObjectName("Empty")
            self.content.addWidget(empty)
        current_day = None
        for day, batch_ids, members in batches:
            if day != current_day:
                current_day = day
                self.content.addWidget(section(day_label(day)))
            self.content.addWidget(self._batch_card(batch_ids, members))
        rate = journal.acceptance_rate()
        self.footer.setText(("Propositions acceptées sans modification : " + f"{rate:.0%}".replace("%", " %") + ". "
                             if rate is not None else "") + "En cas de problème, le journal reste lisible et "
                            "restaurable même sans l'application (voir le README).")
        for index in range(self.content.count()):
            widget = self.content.itemAt(index).widget()
            if widget:
                widget.show()

    def _batch_card(self, batch_ids: list[str], members: list[dict]) -> QFrame:
        batch_id = batch_ids[0]
        # le dossier tampon (_TriBin/a_trier) est une mécanique interne : pas de ligne pour sa création
        members = [o for o in members if not (o.get("action") == "mkdir"
                                              and relative(o.get("destination"), o.get("root")).startswith(STAGING_DIRNAME))]
        kinds = [op_kind(o) for o in members]
        moves = [o for o, k in zip(members, kinds) if k in {"moved", "edited"} or (k == "undone" and o.get("action") == "move")]
        stages = [o for o in members if o.get("action") == "stage"]
        undone = all(k in {"undone", "mkdir"} for k in kinds) and "undone" in kinds
        failed = kinds.count("failed")
        time = members[0].get("ts", "")[11:16]
        if moves:
            title = f"{time} · {plural(len(moves), 'fichier')} rangé{'s' if len(moves) > 1 else ''}"
        elif stages:
            title = f"{time} · {plural(len(stages), 'fichier')} déposé{'s' if len(stages) > 1 else ''} dans la corbeille"
        else:
            title = f"{time} · {plural(len(members), 'opération')}"
        if undone:
            title += ", puis annulé" + ("s" if len(moves or stages) > 1 else "")
        decisions = [o.get("decision") for o in members if o.get("action") == "move" and not o.get("version_archive")]
        details = []
        if decisions.count("accepted"):
            details.append(f"{plural(decisions.count('accepted'), 'proposition')} acceptée"
                           f"{'s' if decisions.count('accepted') > 1 else ''} telle{'s' if decisions.count('accepted') > 1 else ''} quelle{'s' if decisions.count('accepted') > 1 else ''}")
        changed = decisions.count("edited") + decisions.count("alternative_chosen")
        if changed:
            details.append(f"{changed} modifiée{'s' if changed > 1 else ''} par toi")
        if failed:
            details.append(f"{plural(failed, 'échec')}")

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QFrame()
        head.setObjectName("BatchHead")
        head.setStyleSheet(f"QFrame#BatchHead {{ border: none; border-bottom: 1px solid {BORDER}; background: transparent; }}")
        row = QHBoxLayout(head)
        row.setContentsMargins(20, 14, 16, 14)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        color = FAINT if undone else CORAL if failed else TEAL
        dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        row.addWidget(dot)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 700; background: transparent;")
        texts.addWidget(heading)
        if details:
            sub = QLabel(" · ".join(details))
            sub.setObjectName("Muted")
            texts.addWidget(sub)
        row.addLayout(texts, 1)
        undoable = [o for o in members if o.get("status") == "done" and o.get("action") in REVERSIBLE]
        if undone:
            tag = QLabel("ANNULÉ")
            tag.setStyleSheet("background: #ECEEF4; color: #5B6080; border-radius: 11px; padding: 3px 10px; font-weight: 700;")
            row.addWidget(tag)
        elif undoable:
            button = QPushButton("↺  Annuler le lot")
            button.clicked.connect(lambda _=False, b=tuple(batch_ids): self._undo(batch_ids=b))
            row.addWidget(button)
        layout.addWidget(head)

        rows = QVBoxLayout()
        rows.setContentsMargins(20, 6, 16, 10)
        rows.setSpacing(0)
        visible = members if batch_id in self.expanded else members[:VISIBLE_ROWS]
        for op, kind in zip(visible, kinds):
            rows.addWidget(self._op_row(op, kind))
        if len(members) > VISIBLE_ROWS and batch_id not in self.expanded:
            more = QPushButton(f"Voir les {len(members) - VISIBLE_ROWS} autres opérations")
            more.setObjectName("Link")
            more.clicked.connect(lambda _=False, b=batch_id: (self.expanded.add(b), self.reload()))
            rows.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(rows)
        return card

    def _op_row(self, op: dict, kind: str) -> QWidget:
        label, color = KINDS[kind]
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 8, 0, 8)
        line.setSpacing(14)
        tag = QLabel(label)
        tag.setFixedWidth(100)
        tag.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
        line.addWidget(tag)
        target = QLabel(relative(op.get("destination"), op.get("root")))
        target.setFont(mono_font())
        target.setWordWrap(True)
        target.setToolTip(op.get("destination") or "")
        target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        line.addWidget(target, 1)
        if kind == "edited" and op.get("ai_proposal"):
            ai_folder = (op["ai_proposal"].get("target_folder") or "").rsplit("/", 1)[-1]
            hint = f"l'IA proposait {ai_folder}"
        elif kind == "archived":
            hint = "ancienne version"
        elif kind == "failed":
            hint = op.get("error") or ""
        elif op.get("source"):
            hint = f"depuis {Path(op['source']).name}"
        else:
            hint = ""
        if hint:
            note = QLabel()
            note.setObjectName("Muted")
            note.setText(elided(hint, note, 230))
            note.setToolTip(hint)
            line.addWidget(note)
        if op.get("status") == "done" and op.get("action") in REVERSIBLE:
            undo = QPushButton("Annuler")
            undo.setObjectName("Link")
            undo.setToolTip("Annuler cette opération seulement")
            undo.clicked.connect(lambda _=False, o=op["operation_id"]: self._undo(operation_id=o))
            line.addWidget(undo)
        return row

    # --- annulation ---------------------------------------------------------------------------

    def _undo(self, batch_ids: tuple[str, ...] = (), operation_id: str | None = None) -> None:
        targets = [{"operation_id": operation_id}] if operation_id else [{"batch_id": b} for b in batch_ids]
        try:
            executor = self.c.service.executor()
            preview = [r for t in targets for r in executor.undo(execute=False, **t)]
        except Exception as exc:
            QMessageBox.warning(self, "Annulation impossible", str(exc))
            return
        if not preview:
            QMessageBox.information(self, "TriBin", "Rien à annuler pour cette sélection.")
            return
        possible = [r for r in preview if r["status"] == "would_undo"]
        lines = [f"• {Path(r['from']).name} → {r['to'] or '—'}" for r in possible[:20]]
        skipped = [r for r in preview if r["status"] == "ignored"]
        text = f"{plural(len(possible), 'opération')} à annuler :\n\n" + "\n".join(lines)
        if skipped:
            text += f"\n\n{plural(len(skipped), 'opération')} ignorée{'s' if len(skipped) > 1 else ''} " \
                    "(fichier déplacé ou modifié depuis, ou dossier non vide)."
        if QMessageBox.question(self, "Annuler ?", text) != QMessageBox.StandardButton.Yes:
            return
        results = [r for t in targets for r in executor.undo(execute=True, **t)]
        problems = [r for r in results if r["status"] == "failed"]
        if problems:
            QMessageBox.warning(self, "Annulation partielle", "\n".join(f"{r['from']} : {r['message']}" for r in problems))
        self.c.refresh_queue()
        self.reload()
        self.c.bin_window.statusBar().showMessage(
            f"{plural(len([r for r in results if r['status'] == 'undone']), 'opération')} annulée(s) — "
            f"{datetime.now():%H:%M}", 8000)
