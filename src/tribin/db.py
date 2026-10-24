"""Base SQLite locale : profils de dossiers, file d'attente, corrections, règles apprises, réglages."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS folder_profiles (
    root TEXT NOT NULL,
    rel TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    extensions TEXT NOT NULL DEFAULT '[]',
    samples TEXT NOT NULL DEFAULT '[]',
    last_modified REAL,
    patterns TEXT NOT NULL DEFAULT '{}',
    description TEXT NOT NULL DEFAULT '',
    scanned_at TEXT NOT NULL,
    PRIMARY KEY (root, rel)
);
CREATE TABLE IF NOT EXISTS queue (
    file_id TEXT PRIMARY KEY,
    root TEXT NOT NULL,
    original_path TEXT NOT NULL,
    staged_path TEXT NOT NULL,
    stage_operation_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    proposal TEXT,
    error TEXT,
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    original_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    client_hint TEXT,
    ai_folder TEXT,
    ai_name TEXT,
    final_folder TEXT NOT NULL,
    final_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    changed_fields TEXT NOT NULL DEFAULT '[]',
    contradicts_team INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'explicit'
);
CREATE TABLE IF NOT EXISTS learned_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS placed_files (
    operation_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    root TEXT NOT NULL,
    folder TEXT NOT NULL,
    name TEXT NOT NULL,
    original_name TEXT NOT NULL,
    client_hint TEXT,
    placed_at TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    """Accès SQLite partagé entre fils d'exécution (verrou interne)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()

    @contextmanager
    def tx(self):
        """Transaction : validée à la sortie, annulée en cas d'erreur."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- réglages ---------------------------------------------------------------------------

    def get_setting(self, key: str, default=None):
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, json.dumps(value, ensure_ascii=False)))
