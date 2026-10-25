"""Profils de dossiers : motifs de nommage, stockage SQLite, descriptions générées par l'IA."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from tribin.convention.naming import split_extension
from tribin.db import Database
from tribin.llm.base import LLMError, LLMProvider

log = logging.getLogger(__name__)

DESCRIBE_BATCH = 30

DATE_FORMATS = [
    ("AAAA-MM-JJ", re.compile(r"(?<!\d)(19|20)\d{2}-[01]\d-[0-3]\d(?!\d)")),
    ("AAAAMMJJ", re.compile(r"(?<!\d)(19|20)\d{2}[01]\d[0-3]\d(?!\d)")),
    ("JJ-MM-AAAA", re.compile(r"(?<!\d)[0-3]\d[-.][01]\d[-.](19|20)\d{2}(?!\d)")),
    ("AAAA_MM_JJ", re.compile(r"(?<!\d)(19|20)\d{2}_[01]\d_[0-3]\d(?!\d)")),
]
VERSION_TOKENS = re.compile(r"(?:^|[_\-\s.])(v\d{1,3}|V\d{1,3}|final|finale|def|ok|valide)(?=$|[_\-\s.(])", re.IGNORECASE)


class FolderProfile(BaseModel):
    rel: str
    file_count: int = 0
    extensions: list[str] = Field(default_factory=list)
    samples: list[str] = Field(default_factory=list)
    last_modified: float | None = None
    patterns: dict[str, str] = Field(default_factory=dict)
    description: str = ""

    def auto_description(self) -> str:
        """Description de secours, sans IA."""
        if not self.file_count:
            return "dossier vide"
        exts = ", ".join(e.lstrip(".") for e in self.extensions[:3])
        example = f", ex. {self.samples[0]}" if self.samples else ""
        return f"{self.file_count} fichier(s) ({exts}){example}"


def detect_patterns(names: list[str]) -> dict[str, str]:
    """Motifs de nommage dominants d'une liste de noms : format et position de la date, séparateur, versions."""
    if not names:
        return {}
    stems = [split_extension(n)[0] for n in names]
    found: dict[str, str] = {}
    formats: Counter[str] = Counter()
    positions: Counter[str] = Counter()
    seps: Counter[str] = Counter()
    for stem in stems:
        for label, regex in DATE_FORMATS:
            match = regex.search(stem)
            if match:
                formats[label] += 1
                positions["début" if match.start() == 0 else "fin" if match.end() == len(stem) else "milieu"] += 1
                # Le caractère qui suit (ou précède) la date est le séparateur de segments.
                neighbor = stem[match.end():match.end() + 1] or stem[match.start() - 1:match.start()]
                if neighbor in "_- .":
                    seps[neighbor] += 3
                stem = stem[:match.start()] + stem[match.end():]
                break
        seps.update(ch for ch in stem if ch in "_ .")
    if formats:
        label, count = formats.most_common(1)[0]
        found["date_format"] = label
        found["date_position"] = positions.most_common(1)[0][0]
        found["date_share"] = f"{100 * count // len(stems)}%"
    if not seps:
        seps.update(ch for stem in stems for ch in stem if ch == "-")
    if seps:
        found["separator"] = {" ": "espace"}.get(seps.most_common(1)[0][0], seps.most_common(1)[0][0])
    versions = Counter(m.group(1).lower() for stem in stems for m in VERSION_TOKENS.finditer(stem))
    if versions:
        found["version_tokens"] = ", ".join(t for t, _ in versions.most_common(4))
    return found


# --- stockage ---------------------------------------------------------------------------------


def save_profiles(db: Database, root: Path, profiles: list[FolderProfile], keep_descriptions: bool = True) -> None:
    """Remplace les profils d'une racine ; conserve les descriptions existantes des dossiers inchangés."""
    key = str(Path(root).resolve())
    old = {p.rel: p.description for p in load_profiles(db, root)} if keep_descriptions else {}
    now = datetime.now().isoformat(timespec="seconds")
    with db.tx() as c:
        c.execute("DELETE FROM folder_profiles WHERE root=?", (key,))
        c.executemany(
            "INSERT INTO folder_profiles(root, rel, file_count, extensions, samples, last_modified, patterns, "
            "description, scanned_at) VALUES(?,?,?,?,?,?,?,?,?)",
            [(key, p.rel, p.file_count, json.dumps(p.extensions), json.dumps(p.samples, ensure_ascii=False),
              p.last_modified, json.dumps(p.patterns, ensure_ascii=False), p.description or old.get(p.rel, ""), now)
             for p in profiles],
        )


def load_profiles(db: Database, root: Path) -> list[FolderProfile]:
    rows = db.query("SELECT * FROM folder_profiles WHERE root=? ORDER BY rel", (str(Path(root).resolve()),))
    return [FolderProfile(rel=r["rel"], file_count=r["file_count"], extensions=json.loads(r["extensions"]),
                          samples=json.loads(r["samples"]), last_modified=r["last_modified"],
                          patterns=json.loads(r["patterns"]), description=r["description"]) for r in rows]


def light_update(db: Database, root: Path, fresh: list[FolderProfile]) -> tuple[list[str], list[str]]:
    """Mise à jour légère au lancement : ajoute les nouveaux dossiers, retire les disparus, et rafraîchit compteurs,
    échantillons et motifs des dossiers connus (seule la description, rédigée par l'IA, est conservée)."""
    old = {p.rel: p for p in load_profiles(db, root)}
    new = {p.rel: p for p in fresh}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = any(r in new and (old[r].file_count, old[r].samples, old[r].extensions) !=
                  (new[r].file_count, new[r].samples, new[r].extensions) for r in old)
    if added or removed or changed:
        merged = [new[r].model_copy(update={"description": old[r].description}) for r in old if r in new] + \
                 [new[r] for r in added]
        save_profiles(db, root, merged)
    return added, removed


# --- descriptions par l'IA --------------------------------------------------------------------


class FolderDescription(BaseModel):
    rel: str
    description: str


class FolderDescriptions(BaseModel):
    items: list[FolderDescription]


DESCRIBE_SYSTEM = (
    "Tu décris des dossiers de travail d'une agence. Pour chaque dossier, écris une description courte en français "
    "(8 à 15 mots) qui dit ce qu'il contient, d'après son chemin et ses fichiers échantillons. "
    "Exemple : « Factures fournisseurs 2025, une par fournisseur ». Réponds uniquement en JSON."
)


def describe_profiles(profiles: list[FolderProfile], llm: LLMProvider, only_missing: bool = True) -> int:
    """Génère les descriptions par lots de 30 dossiers par appel. Renvoie le nombre de dossiers décrits."""
    todo = [p for p in profiles if not (only_missing and p.description)]
    done = 0
    for start in range(0, len(todo), DESCRIBE_BATCH):
        batch = todo[start:start + DESCRIBE_BATCH]
        lines = [f"- {p.rel} | {p.file_count} fichiers | ex. : {', '.join(p.samples) or '(vide)'}" for p in batch]
        user = ("Dossiers (chemin | nombre de fichiers | échantillons) :\n" + "\n".join(lines)
                + '\n\nRéponds avec {"items": [{"rel": "chemin exact", "description": "..."}]}')
        try:
            result = llm.complete_json(DESCRIBE_SYSTEM, user, FolderDescriptions)
        except LLMError as exc:
            log.warning("folder description batch failed: %s", exc)
            continue
        by_rel = {item.rel.strip("/"): item.description.strip() for item in result.items}
        for p in batch:
            if by_rel.get(p.rel):
                p.description = by_rel[p.rel]
                done += 1
    return done
