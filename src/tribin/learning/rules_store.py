"""Règles apprises (lisibles, modifiables et supprimables par l'utilisateur).

Trois sortes de règles, toutes données à l'IA quand elles sont actives :
- « learned » : tirées de vos corrections (synthèse par l'IA) ;
- « confirmed » : confirmées par vos validations sans modification (même type de fichier, même dossier) ;
- « manual » : ajoutées par vous.
Chaque règle garde sa logique (`details`) : les corrections ou validations d'où elle vient.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from tribin.db import Database

KINDS = {"learned": "Apprise de vos corrections", "confirmed": "Confirmée par vos validations",
         "manual": "Ajoutée par vous"}
TEXT_TAGS = {"learned": "[apprise]", "confirmed": "[confirmée]", "manual": "[ajoutée]"}
DISMISSED_KEY = "dismissed_rules"  # règles confirmées supprimées par l'utilisateur : ne pas les recréer
CONFIRM_MIN = 2  # validations sans modification nécessaires pour confirmer une règle


@dataclass
class Rule:
    id: int
    text: str
    enabled: bool
    kind: str = "learned"
    details: dict = field(default_factory=dict)
    created_at: str = ""
    rule_key: str | None = None

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, "Règle")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _rule(r) -> Rule:
    try:
        details = json.loads(r["details"] or "{}")
    except (TypeError, ValueError):
        details = {}
    return Rule(r["id"], r["text"], bool(r["enabled"]), r["kind"] or "learned", details, r["created_at"] or "",
                r["rule_key"])


def list_rules(db: Database, only_enabled: bool = False, kind: str | None = None) -> list[Rule]:
    where, params = [], []
    if only_enabled:
        where.append("enabled=1")
    if kind:
        where.append("kind=?")
        params.append(kind)
    sql = "SELECT * FROM learned_rules" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
    return [_rule(r) for r in db.query(sql, tuple(params))]


def add_rule(db: Database, text: str, kind: str = "manual", details: dict | None = None,
             rule_key: str | None = None) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO learned_rules(text, created_at, kind, details, rule_key, updated_at) "
                  "VALUES(?, ?, ?, ?, ?, ?)",
                  (text.strip(), _now(), kind, json.dumps(details or {}, ensure_ascii=False), rule_key, _now()))


def update_rule(db: Database, rule_id: int, text: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE learned_rules SET text=?, updated_at=? WHERE id=?", (text.strip(), _now(), rule_id))


def set_enabled(db: Database, rule_id: int, enabled: bool) -> None:
    with db.tx() as c:
        c.execute("UPDATE learned_rules SET enabled=?, updated_at=? WHERE id=?", (int(enabled), _now(), rule_id))


def delete_rule(db: Database, rule_id: int) -> None:
    rows = db.query("SELECT rule_key FROM learned_rules WHERE id=?", (rule_id,))
    if rows and rows[0]["rule_key"]:  # règle confirmée supprimée : ne pas la recréer à la prochaine validation
        dismissed = set(db.get_setting(DISMISSED_KEY, []) or [])
        dismissed.add(rows[0]["rule_key"])
        db.set_setting(DISMISSED_KEY, sorted(dismissed))
    with db.tx() as c:
        c.execute("DELETE FROM learned_rules WHERE id=?", (rule_id,))


def replace_rules(db: Database, texts: list[str], details: dict | None = None) -> None:
    """Remplace les règles tirées des corrections par une nouvelle synthèse (les autres sont gardées)."""
    now = _now()
    payload = json.dumps(details or {}, ensure_ascii=False)
    with db.tx() as c:
        c.execute("DELETE FROM learned_rules WHERE kind='learned'")
        c.executemany("INSERT INTO learned_rules(text, created_at, kind, details, updated_at) VALUES(?, ?, 'learned', ?, ?)",
                      [(t.strip(), now, payload, now) for t in texts if t.strip()])


# --- règles confirmées par les validations -----------------------------------------------------------


def refresh_confirmed_rules(db: Database) -> int:
    """Crée les règles confirmées : même modèle de nom validé sans modification plusieurs fois vers le même
    dossier. Met à jour leur compte ; ne recrée jamais une règle supprimée. Renvoie le nombre de règles ajoutées."""
    from tribin.engine.similar import distinctive_words, name_pattern
    from tribin.learning.corrections import list_corrections

    groups: dict[str, list] = {}
    for corr in list_corrections(db, 2000):
        if corr.decision != "accepted" or not corr.final_folder or not distinctive_words(corr.original_name):
            continue
        groups.setdefault(f"{name_pattern(corr.original_name)}|{corr.final_folder}", []).append(corr)
    dismissed = set(db.get_setting(DISMISSED_KEY, []) or [])
    existing = {r.rule_key: r for r in list_rules(db, kind="confirmed") if r.rule_key}
    added = 0
    for key, members in groups.items():
        if len(members) < CONFIRM_MIN or key in dismissed:
            continue
        folder = members[0].final_folder
        details = {"count": len(members), "folder": folder,
                   "examples": [f"« {c.original_name} » → {c.final_folder}/{c.final_name}" for c in members[:8]]}
        if key in existing:
            with db.tx() as c:
                c.execute("UPDATE learned_rules SET details=? WHERE id=?",
                          (json.dumps(details, ensure_ascii=False), existing[key].id))
            continue
        text = f"Les fichiers nommés comme « {members[0].original_name} » vont dans « {folder} »."
        add_rule(db, text, "confirmed", details, rule_key=key)
        added += 1
    return added


# --- vue texte -----------------------------------------------------------------------------------------


def rules_as_text(db: Database) -> str:
    """Une règle par ligne, précédée de sa sorte ; « # » au début : règle désactivée."""
    return "\n".join(f"{'' if r.enabled else '# '}{TEXT_TAGS.get(r.kind, '')} {r.text}".strip()
                     for r in list_rules(db))


def apply_text(db: Database, text: str) -> None:
    """Enregistre la vue texte : les règles inchangées gardent leur logique, les nouvelles lignes deviennent des
    règles ajoutées par vous, les lignes retirées sont supprimées."""
    tags = {tag: kind for kind, tag in TEXT_TAGS.items()}
    current = list_rules(db)
    by_text = {r.text: r for r in current}
    kept: set[int] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        enabled = not line.startswith("#")
        line = line.lstrip("#").strip()
        for tag in tags:
            if line.startswith(tag):
                line = line[len(tag):].strip()
        if not line:
            continue
        rule = by_text.get(line)
        if rule and rule.id not in kept:
            kept.add(rule.id)
            if rule.enabled != enabled:
                set_enabled(db, rule.id, enabled)
            continue
        add_rule(db, line, "manual")  # une ligne nouvelle (ou modifiée) devient une règle ajoutée par vous
        if not enabled:
            set_enabled(db, list_rules(db)[-1].id, False)
        kept.add(list_rules(db)[-1].id)
    for rule in current:
        if rule.id not in kept:
            delete_rule(db, rule.id)
