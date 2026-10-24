"""Historique : opérations du journal, filtrables par date ou par lot, annulables."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tribin.safety.journal import Journal
from tribin.ui.theme import header_bar

if TYPE_CHECKING:
    from tribin.ui.app import AppController

ACTIONS_FR = {"stage": "Dépôt", "mkdir": "Dossier créé", "move": "Rangement", "rename": "Renommage",
              "archive": "Archivage", "undo": "Annulation"}
STATUS_FR = {"done": "fait", "failed": "échec", "skipped": "ignoré", "undone": "annulé", "pending": "en cours"}


class HistoryWindow(QDialog):
    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.ops: list[dict] = []
        self.setWindowTitle("TriBin — Historique")
        self.resize(1100, 520)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Depuis le"))
        self.since = QDateEdit(QDate.currentDate().addDays(-30))
        self.since.setCalendarPopup(True)
        self.since.dateChanged.connect(self.reload)
        filters.addWidget(self.since)
        filters.addWidget(QLabel("Lot"))
        self.batch = QLineEdit()
        self.batch.setPlaceholderText("identifiant de lot (facultatif)")
        self.batch.textChanged.connect(self.reload)
        filters.addWidget(self.batch)
        filters.addStretch()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Action", "Statut", "Source", "Destination", "Lot"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        for column in (0, 1, 2, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        buttons = QHBoxLayout()
        undo_op = QPushButton("Annuler l'opération")
        undo_op.clicked.connect(lambda: self._undo(batch=False))
        undo_batch = QPushButton("Annuler le lot")
        undo_batch.clicked.connect(lambda: self._undo(batch=True))
        self.rate = QLabel()
        buttons.addWidget(undo_op)
        buttons.addWidget(undo_batch)
        buttons.addStretch()
        buttons.addWidget(self.rate)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(header_bar("Historique", "Toutes les opérations sont annulables"))
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(body, 1)
        layout.addLayout(filters)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        journal = Journal(self.c.service.settings.journal_dir)
        since = self.since.date().toString("yyyy-MM-dd")
        batch = self.batch.text().strip() or None
        self.ops = [op for op in journal.operations(batch_id=batch) if op.get("ts", "")[:10] >= since]
        self.table.setRowCount(len(self.ops))
        for row, op in enumerate(self.ops):
            values = [op.get("ts", "")[:19].replace("T", " "), ACTIONS_FR.get(op.get("action"), op.get("action", "")),
                      STATUS_FR.get(op.get("status"), op.get("status", "")), op.get("source") or "",
                      op.get("destination") or "", op.get("batch_id", "")]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(self._short(value, op) if col in (3, 4) else value)
                if col in (3, 4) and value:
                    cell.setToolTip(value)
                if op.get("error"):
                    cell.setToolTip(op["error"])
                self.table.setItem(row, col, cell)
        rate = journal.acceptance_rate()
        self.rate.setText(f"Propositions acceptées sans modification : {rate:.0%}" if rate is not None else "")

    @staticmethod
    def _short(path: str, op: dict) -> str:
        """Chemin relatif à la racine quand c'est possible (plus lisible), sinon chemin complet."""
        root = op.get("root")
        if path and root:
            try:
                return Path(path).relative_to(Path(root)).as_posix()
            except ValueError:
                pass
        return path

    def _undo(self, batch: bool) -> None:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if not rows:
            return
        op = self.ops[rows[0]]
        kwargs = {"batch_id": op.get("batch_id")} if batch else {"operation_id": op["operation_id"]}
        try:
            executor = self.c.service.executor()
            preview = executor.undo(execute=False, **kwargs)
        except Exception as exc:
            QMessageBox.warning(self, "Annulation impossible", str(exc))
            return
        if not preview:
            QMessageBox.information(self, "TriBin", "Rien à annuler pour cette sélection.")
            return
        lines = [f"• {ACTIONS_FR.get(r['action'], r['action'])} : {r['from']} → {r['to'] or '—'} {r['message']}"
                 for r in preview]
        answer = QMessageBox.question(self, "Confirmer l'annulation", "Simulation :\n\n" + "\n".join(lines[:30])
                                      + ("\n…" if len(lines) > 30 else "") + "\n\nAnnuler ces opérations ?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        results = executor.undo(execute=True, **kwargs)
        problems = [r for r in results if r["status"] not in {"undone"}]
        if problems:
            QMessageBox.warning(self, "Annulation partielle", "\n".join(
                f"{r['from']} : {r['message']}" for r in problems))
        self.c.refresh_queue()
        self.reload()
