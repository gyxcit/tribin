"""File d'attente persistante de la corbeille (les fichiers en attente survivent à un redémarrage)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from tribin.db import Database
from tribin.models import Proposal

# Statuts : analyzing (analyse en cours) · ready (proposition prête) · error · done (rangé) · returned (renvoyé)
ACTIVE = ("analyzing", "ready", "error")


class QueueItem(BaseModel):
    file_id: str
    root: str
    original_path: str
    staged_path: str
    stage_operation_id: str | None = None
    status: str = "analyzing"
    proposal: Proposal | None = None
    error: str | None = None
    added_at: str = ""

    @property
    def name(self) -> str:
        return self.staged_path.replace("\\", "/").rsplit("/", 1)[-1]


class QueueStore:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, item: QueueItem) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        item.added_at = item.added_at or now
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO queue(file_id, root, original_path, staged_path, stage_operation_id, status, proposal, "
                "error, added_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(file_id) DO UPDATE SET "
                "root=excluded.root, original_path=excluded.original_path, staged_path=excluded.staged_path, "
                "stage_operation_id=excluded.stage_operation_id, status=excluded.status, proposal=excluded.proposal, "
                "error=excluded.error, updated_at=excluded.updated_at",
                (item.file_id, item.root, item.original_path, item.staged_path, item.stage_operation_id, item.status,
                 item.proposal.model_dump_json() if item.proposal else None, item.error, item.added_at, now),
            )

    def get(self, file_id: str) -> QueueItem | None:
        rows = self.db.query("SELECT * FROM queue WHERE file_id=?", (file_id,))
        return self._item(rows[0]) if rows else None

    def active(self) -> list[QueueItem]:
        marks = ",".join("?" * len(ACTIVE))
        rows = self.db.query(f"SELECT * FROM queue WHERE status IN ({marks}) ORDER BY added_at, file_id", ACTIVE)
        return [self._item(r) for r in rows]

    def set_status(self, file_id: str, status: str, error: str | None = None) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE queue SET status=?, error=?, updated_at=? WHERE file_id=?",
                      (status, error, datetime.now().isoformat(timespec="seconds"), file_id))

    @staticmethod
    def _item(row) -> QueueItem:
        return QueueItem(
            file_id=row["file_id"], root=row["root"], original_path=row["original_path"], staged_path=row["staged_path"],
            stage_operation_id=row["stage_operation_id"], status=row["status"],
            proposal=Proposal.model_validate_json(row["proposal"]) if row["proposal"] else None,
            error=row["error"], added_at=row["added_at"],
        )
