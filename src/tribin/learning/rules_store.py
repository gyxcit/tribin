"""Règles apprises (lisibles, modifiables et supprimables par l'utilisateur)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tribin.db import Database


@dataclass
class Rule:
    id: int
    text: str
    enabled: bool


def list_rules(db: Database, only_enabled: bool = False) -> list[Rule]:
    sql = "SELECT id, text, enabled FROM learned_rules" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id"
    return [Rule(r["id"], r["text"], bool(r["enabled"])) for r in db.query(sql)]


def add_rule(db: Database, text: str) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO learned_rules(text, created_at) VALUES(?, ?)",
                  (text.strip(), datetime.now().isoformat(timespec="seconds")))


def update_rule(db: Database, rule_id: int, text: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE learned_rules SET text=? WHERE id=?", (text.strip(), rule_id))


def delete_rule(db: Database, rule_id: int) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM learned_rules WHERE id=?", (rule_id,))


def replace_rules(db: Database, texts: list[str]) -> None:
    """Remplace les règles générées par une nouvelle synthèse."""
    now = datetime.now().isoformat(timespec="seconds")
    with db.tx() as c:
        c.execute("DELETE FROM learned_rules")
        c.executemany("INSERT INTO learned_rules(text, created_at) VALUES(?, ?)", [(t.strip(), now) for t in texts if t.strip()])
