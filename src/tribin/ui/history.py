"""Historique, fichier par fichier : chaque ligne (nom, statut, heure) se déplie sur ses détails — date, dossier,
catégorie, confiance de l'IA, décision — avec « Ouvrir », « Afficher » et l'annulation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tribin.safety.journal import Journal
from tribin.service.activity import CORRECTED, Placement, placements
from tribin.ui.components import FileBadge, Pill, elided, muted, section
from tribin.ui.icons import line_icon
from tribin.ui.system_integration import FILE_MANAGER, reveal, reveal_target
from tribin.ui.theme import level_for, mono_font

if TYPE_CHECKING:
    from tribin.ui.app import AppController

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
REVERSIBLE = {"stage", "move", "rename", "archive", "mkdir"}
MAX_ITEMS = 200

# Pastille de statut : (libellé, fond, texte)
PILLS = {
    "accepted": ("Rangé", "#DDF5F1", "#0F766E"),
    "auto": ("Automatique", "#E3E7FB", "#2F3BA0"),
    "corrected": ("Corrigé", "#FDF0D5", "#8A4B05"),
    "reorganisation": ("Réorganisé", "#ECEEF4", "#5B6080"),
    "undone": ("Annulé", "#ECEEF4", "#5B6080"),
    "failed": ("Échec", "#FDE4E2", "#A42A25"),
    "staged": ("Déposé", "#ECEEF4", "#3A4063"),
    "returned": ("Renvoyé", "#ECEEF4", "#5B6080"),
}


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


def long_date(when: datetime) -> str:
    return f"{DAYS[when.weekday()]} {when.day} {MONTHS[when.month - 1]} {when.year} à {when:%H:%M}"


def relative(path: str | None, root: str | None) -> str:
    if path and root:
        try:
            return Path(path).relative_to(Path(root)).as_posix()
        except ValueError:
            pass
    return path or ""


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def pill_key(p: Placement) -> str:
    if p.status in {"undone", "failed"}:
        return p.status
    if p.decision in CORRECTED:
        return "corrected"
    return p.decision if p.decision in PILLS else "accepted"


class _Clicks(QObject):
    """Clic sur l'en-tête : déplier ; double-clic : ouvrir le fichier."""

    def __init__(self, row: ExpandableRow):
        super().__init__(row)
        self.row = row

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — API Qt
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.row.toggle()
            return True
        if event.type() == QEvent.Type.MouseButtonDblClick and self.row.on_open:
            self.row.on_open()
            return True
        return False


class ExpandableRow(QFrame):
    """Ligne d'historique : en-tête (chevron, type, nom, statut, heure) et détails dépliables."""

    def __init__(self, key: str, name: str, badge_path: Path, pill: tuple[str, str, str], time_text: str,
                 expanded: bool, on_toggle, on_open=None):
        super().__init__()
        self.setObjectName("HistRow")
        self.key, self.on_toggle, self.on_open = key, on_toggle, on_open
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.head = QFrame()
        self.head.setObjectName("HistHead")
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.setToolTip("Cliquer pour voir les détails · double-cliquer pour ouvrir le fichier")
        line = QHBoxLayout(self.head)
        line.setContentsMargins(12, 10, 16, 10)
        line.setSpacing(12)
        self.chevron = QLabel()
        line.addWidget(self.chevron)
        badge = FileBadge(30)
        badge.set_path(badge_path)
        line.addWidget(badge)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight: 600;")
        self.name.setText(elided(name, self.name, 520, Qt.TextElideMode.ElideMiddle))
        self.name.setToolTip(name)
        line.addWidget(self.name, 1)
        label, background, text = pill
        line.addWidget(Pill(label, (background, text)))
        when = muted(time_text, wrap=False)
        when.setMinimumWidth(44)
        when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(when)
        outer.addWidget(self.head)
        self.head.installEventFilter(_Clicks(self))

        self.details = QWidget()
        box = QVBoxLayout(self.details)
        box.setContentsMargins(56, 4, 16, 14)
        box.setSpacing(12)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnMinimumWidth(0, 130)
        self.grid.setColumnStretch(1, 1)
        box.addLayout(self.grid)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        box.addLayout(self.actions)
        outer.addWidget(self.details)
        self.set_expanded(expanded)

    def add_detail(self, label: str, value: str, mono: bool = False, tooltip: str = "") -> None:
        row = self.grid.rowCount()
        key = muted(label, wrap=False)
        text = QLabel(value)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if mono:
            text.setFont(mono_font())
        if tooltip:
            text.setToolTip(tooltip)
        self.grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(text, row, 1)

    def add_action(self, button: QPushButton) -> None:
        self.actions.addWidget(button)

    def finish(self) -> None:
        self.actions.addStretch()

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.details.setVisible(expanded)
        self.chevron.setPixmap(line_icon("chevron-down" if expanded else "chevron-right", "#5B6080", 16)
                               .pixmap(16, 16))
        self.setProperty("open", "true" if expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def toggle(self) -> None:
        self.set_expanded(not self.expanded)
        self.on_toggle(self.key, self.expanded)


def action_button(text: str, icon: str = "", primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Primary" if primary else "Small")
    if icon:
        button.setIcon(line_icon(icon, "#FFFFFF" if primary else "#1F2544", 15))
    return button


def open_file(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class HistoryView(QWidget):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.expanded: set[str] = set()
        self.setStyleSheet("""
            QFrame#HistList { background: white; border: 1px solid #E2E5EF; border-radius: 12px; }
            QFrame#HistRow { background: transparent; border: none; border-top: 1px solid #EEF0F6; }
            QFrame#HistRow[open="true"] { background: #F7F8FC; }
            QFrame#HistHead { background: transparent; border: none; }
            QFrame#HistHead:hover { background: #F7F8FC; }
            QFrame#HistRow QLabel { background: transparent; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        wrapper = QHBoxLayout(page)
        wrapper.setContentsMargins(28, 24, 28, 24)
        column_box = QWidget()
        column_box.setMaximumWidth(1080)
        wrapper.addStretch()
        wrapper.addWidget(column_box, 100)
        wrapper.addStretch()
        self.column = QVBoxLayout(column_box)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(12)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Historique")
        title.setObjectName("Title")
        titles.addWidget(title)
        head.addLayout(titles, 1)
        self.filters = QButtonGroup(self)
        for key, label in (("moves", "Rangements"), ("undone", "Annulés"), ("stages", "Dépôts")):
            button = QPushButton(label)
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setProperty("key", key)
            button.setChecked(key == "moves")
            bold = button.font()
            bold.setBold(True)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(label) + 30)  # sélectionné : en gras, pas coupé
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
        self.content.setSpacing(10)
        self.column.addLayout(self.content)
        self.column.addStretch()

    # --- affichage ----------------------------------------------------------------------------

    def _since(self) -> date | None:
        days = self.period.currentData()
        return date.today() - timedelta(days=days) if days else None

    def _clear(self) -> None:
        while self.content.count():
            widget = self.content.takeAt(0).widget()
            if widget:
                widget.hide()  # sinon visible jusqu'à sa destruction effective
                widget.deleteLater()

    def _toggled(self, key: str, expanded: bool) -> None:
        (self.expanded.add if expanded else self.expanded.discard)(key)

    def reload(self) -> None:
        self._clear()
        journal = Journal(self.c.service.settings.journal_dir)
        mode = self.filters.checkedButton().property("key")
        if mode == "stages":
            groups = self._group([(self._when(op), op) for op in self._stages(journal)])
            noun, verb = "fichier", "déposé"
        else:
            items = [p for p in placements(journal, self._since()) if mode != "undone" or p.status == "undone"]
            groups = self._group([(p.when, p) for p in items[:MAX_ITEMS]])
            noun, verb = "fichier", "annulé" if mode == "undone" else "rangé"
            batch_sizes: dict[str, int] = {}
            for p in items:
                if p.status == "done":
                    batch_sizes[p.batch_id] = batch_sizes.get(p.batch_id, 0) + 1
        if not groups:
            empty = QLabel("Aucun fichier sur cette période.")
            empty.setObjectName("Empty")
            self.content.addWidget(empty)
        for day, members in groups:
            n = len(members)
            self.content.addWidget(section(f"{day_label(day)} · {plural(n, noun)} {verb}{'s' if n > 1 else ''}"))
            card = QFrame()
            card.setObjectName("HistList")
            rows = QVBoxLayout(card)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(0)
            for _, item in members:
                row = self._stage_row(item) if mode == "stages" else self._placement_row(item, batch_sizes)
                rows.addWidget(row)
            first = rows.itemAt(0).widget()
            if first:
                first.setStyleSheet("QFrame#HistRow { border-top: none; }")
            self.content.addWidget(card)
        for index in range(self.content.count()):
            widget = self.content.itemAt(index).widget()
            if widget:
                widget.show()

    @staticmethod
    def _group(items: list[tuple[datetime, object]]) -> list[tuple[str, list[tuple[datetime, object]]]]:
        groups: dict[str, list] = {}
        for when, item in sorted(items, key=lambda x: x[0], reverse=True):
            groups.setdefault(when.date().isoformat(), []).append((when, item))
        return list(groups.items())

    @staticmethod
    def _when(op: dict) -> datetime:
        try:
            return datetime.fromisoformat((op.get("ts") or "")[:19])
        except ValueError:
            return datetime.min

    def _stages(self, journal: Journal) -> list[dict]:
        since = self._since()
        ops = [o for o in journal.operations() if o.get("action") == "stage"
               and o.get("status") in {"done", "undone"}]
        return [o for o in ops if not since or self._when(o).date() >= since][:MAX_ITEMS]

    # --- lignes -------------------------------------------------------------------------------

    def _placement_row(self, p: Placement, batch_sizes: dict[str, int]) -> ExpandableRow:
        label, background, text = PILLS[pill_key(p)]
        current = p.current_path
        row = ExpandableRow(p.operation_id, p.name, p.destination, (label, background, text), f"{p.when:%H:%M}",
                            p.operation_id in self.expanded, self._toggled,
                            on_open=(lambda path=current: open_file(path)) if current and current.is_file() else None)
        row.add_detail("Rangé le", long_date(p.when))
        row.add_detail("Dossier", " › ".join(x for x in p.folder.split("/") if x) or "—", mono=True,
                       tooltip=str(p.destination.parent))
        row.add_detail("Catégorie", p.category or "—")
        row.add_detail("Confiance de l'IA", f"{p.confidence:.0%} · {level_for(p.confidence)[1]}".replace("%", " %")
                       if p.confidence is not None else "—")
        decision = p.decision_label
        if p.decision in CORRECTED and p.ai_folder and p.ai_folder != p.folder:
            decision += f" (l'IA proposait {p.ai_folder.replace('/', ' › ')})"
        row.add_detail("Décision", decision)
        if p.original_name != p.name:
            row.add_detail("Nom d'origine", p.original_name, mono=True)
        if p.status == "undone":
            row.add_detail("Statut", "Rangement annulé : le fichier est revenu dans TriBin.")
        if p.status == "failed":
            row.add_detail("Erreur", p.error or "—")

        open_button = action_button("Ouvrir", "open", primary=True)
        open_button.setEnabled(bool(current and current.is_file()))
        open_button.clicked.connect(lambda _=False, path=current: open_file(path))
        row.add_action(open_button)
        row.add_action(self._reveal_button(reveal_target(current, p.destination)))
        if p.status == "done":
            undo = action_button("Annuler ce rangement", "undo")
            undo.clicked.connect(lambda _=False, o=p.operation_id: self._undo(operation_id=o))
            row.add_action(undo)
            if batch_sizes.get(p.batch_id, 0) > 1:
                batch = action_button(f"Annuler le lot ({batch_sizes[p.batch_id]} fichiers)")
                batch.setObjectName("Link")
                batch.clicked.connect(lambda _=False, b=p.batch_id: self._undo(batch_ids=(b,)))
                row.add_action(batch)
        row.finish()
        return row

    def _stage_row(self, op: dict) -> ExpandableRow:
        undone = op.get("status") == "undone"
        source, destination = Path(op.get("source") or ""), Path(op.get("destination") or "")
        when = self._when(op)
        label, background, text = PILLS["returned" if undone else "staged"]
        row = ExpandableRow(op["operation_id"], source.name or destination.name, destination,
                            (label, background, text), f"{when:%H:%M}", op["operation_id"] in self.expanded,
                            self._toggled)
        row.add_detail("Déposé le", long_date(when))
        row.add_detail("Venait de", str(source.parent), mono=True)
        row.add_detail("En attente dans", relative(op.get("destination"), op.get("root")), mono=True)
        if undone:
            row.add_detail("Statut", "Renvoyé à son emplacement d'origine.")
        row.add_action(self._reveal_button(reveal_target(source if undone else destination, destination)))
        if op.get("status") == "done":
            undo = action_button("Renvoyer à l'origine", "undo")
            undo.clicked.connect(lambda _=False, o=op["operation_id"]: self._undo(operation_id=o))
            row.add_action(undo)
        row.finish()
        return row

    @staticmethod
    def _reveal_button(target: Path | None) -> QPushButton:
        """« Afficher dans l'Explorateur » : le fichier sélectionné, là où il est maintenant."""
        button = action_button(f"Afficher dans {FILE_MANAGER}", "folder")
        if target is None:
            button.setEnabled(False)
            button.setToolTip("Le fichier n'est plus à cet emplacement.")
        else:
            button.setToolTip(str(target))
            button.clicked.connect(lambda _=False, t=target: reveal(t))
        return button

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
        self.c.requeue_returned()  # un rangement annulé revient dans « À ranger »
        self.c.refresh_queue()
        self.reload()
        self.c.bin_window.statusBar().showMessage(
            f"{plural(len([r for r in results if r['status'] == 'undone']), 'opération')} annulée(s) — "
            f"{datetime.now():%H:%M}", 8000)
