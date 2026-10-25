"""Compte TriBin, gardé dans la base SQLite locale.

Pour l'instant un compte « local » (nom, e-mail) ; plus tard, la connexion aux serveurs TriBin remplira
`server_id` (l'identifiant côté serveur) et `kind` passera à « server ».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tribin.db import Database


@dataclass
class Account:
    display_name: str
    email: str = ""
    kind: str = "local"  # local · server (connexion aux serveurs TriBin, à venir)
    server_id: str | None = None
    created_at: str = ""

    @property
    def initials(self) -> str:
        words = [w for w in self.display_name.replace("-", " ").split() if w]
        letters = "".join(w[0] for w in words[:2]) or "?"
        return letters.upper()

    @property
    def status(self) -> str:
        return "Compte connecté" if self.kind == "server" else "Compte local"


def default_name(user: str) -> str:
    """Nom proposé au premier lancement, d'après la session Windows ou macOS (« regis » -> « Regis »)."""
    base = (user or "").split("\\")[-1].split("@")[0].replace(".", " ").replace("_", " ").strip()
    return " ".join(w.capitalize() for w in base.split()) or "Moi"


def get_account(db: Database, user: str = "") -> Account:
    """Le compte de cet ordinateur ; créé au premier appel."""
    rows = db.query("SELECT display_name, email, kind, server_id, created_at FROM account WHERE id=1")
    if rows:
        r = rows[0]
        return Account(r["display_name"], r["email"], r["kind"], r["server_id"], r["created_at"])
    account = Account(default_name(user), created_at=datetime.now().isoformat(timespec="seconds"))
    with db.tx() as c:
        c.execute("INSERT INTO account(id, display_name, email, kind, server_id, created_at) VALUES(1, ?, ?, ?, ?, ?)",
                  (account.display_name, account.email, account.kind, account.server_id, account.created_at))
    return account


def save_account(db: Database, display_name: str, email: str) -> Account:
    get_account(db)  # crée la ligne si besoin
    with db.tx() as c:
        c.execute("UPDATE account SET display_name=?, email=? WHERE id=1",
                  (display_name.strip() or "Moi", email.strip()))
    return get_account(db)
