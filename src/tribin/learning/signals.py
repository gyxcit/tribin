"""Signal implicite (fichier rangé puis déplacé à la main) et règles résumées par l'IA (section 6.7, fin de phase 5)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from tribin.convention.loader import Convention
from tribin.db import Database
from tribin.fs.filters import INTERNAL_DIRS, ExclusionMatcher, nfc
from tribin.learning.corrections import list_corrections, record_correction, usable
from tribin.learning.rules_store import list_rules, replace_rules
from tribin.llm.base import LLMError, LLMProvider
from tribin.models import NameFields, Proposal

log = logging.getLogger(__name__)

IMPLICIT_DAYS = 14
SUMMARY_EVERY = 5  # règles apprises re-synthétisées toutes les 5 corrections
MAX_RULES = 8


def remember_placement(db: Database, operation_id: str, path: Path, root: Path, folder: str, name: str,
                       original_name: str, client_hint: str | None) -> None:
    """Mémorise un fichier rangé par TriBin, pour détecter un déplacement manuel ultérieur."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO placed_files(operation_id, path, size, root, folder, name, original_name, "
                  "client_hint, placed_at, checked) VALUES(?,?,?,?,?,?,?,?,?,0)",
                  (operation_id, str(path), size, str(root), folder, name, original_name, client_hint,
                   datetime.now().isoformat(timespec="seconds")))


def _find_by_name(root: Path, name: str, size: int, matcher: ExclusionMatcher) -> Path | None:
    target = nfc(name).casefold()
    for current, dirs, files in os.walk(root):
        rel = Path(current).relative_to(root).as_posix()
        dirs[:] = [d for d in dirs if d.lower() not in INTERNAL_DIRS and not d.startswith(".")
                   and not matcher.matches_rel(f"{rel}/{d}" if rel != "." else d)]
        for f in files:
            if nfc(f).casefold() == target:
                path = Path(current) / f
                try:
                    if path.stat().st_size == size:
                        return path
                except OSError:
                    continue
    return None


def check_moved_files(db: Database, convention: Convention, now: datetime | None = None) -> int:
    """Au lancement : un fichier rangé par TriBin et déplacé à la main dans les 14 jours devient une correction."""
    now = now or datetime.now()
    matcher = ExclusionMatcher(convention.excluded_paths)
    found = 0
    for row in db.query("SELECT * FROM placed_files WHERE checked=0"):
        placed_at = datetime.fromisoformat(row["placed_at"])
        path, root = Path(row["path"]), Path(row["root"])
        expired = now - placed_at > timedelta(days=IMPLICIT_DAYS)
        if path.exists():
            if expired:
                with db.tx() as c:
                    c.execute("UPDATE placed_files SET checked=1 WHERE operation_id=?", (row["operation_id"],))
            continue
        moved = None if expired else _find_by_name(root, row["name"], row["size"], matcher)
        if moved is not None:
            rel = moved.parent.relative_to(root).as_posix()
            placed = Proposal(file_id=row["operation_id"], target_folder=row["folder"], new_name=row["name"],
                              fields=NameFields(), confidence=1.0, reasoning="", prompt_version="", model="")
            record_correction(db, convention, row["original_name"], "", row["client_hint"], placed, rel, moved.name,
                              "edited", source="implicit")
            found += 1
        with db.tx() as c:
            c.execute("UPDATE placed_files SET checked=1 WHERE operation_id=?", (row["operation_id"],))
    return found


class RulesSummary(BaseModel):
    rules: list[str] = Field(default_factory=list)


SUMMARY_SYSTEM = (
    "Tu résumes les préférences de rangement d'un utilisateur à partir de ses corrections. Écris au plus 8 règles "
    "courtes, concrètes et vérifiables, en français, à la deuxième personne, qui disent dans quel dossier va quel "
    "genre de document (ex. « Tu ranges les devis signés dans 06_Admin ») ou comment tu le décris (ex. « Tu nommes "
    "les relevés par banque et par mois »). Jamais de règle sur le format du nom (date, séparateurs, version, "
    "majuscules) : le nom est assemblé par le programme, pas par toi. N'invente rien. Ne contredis jamais la "
    "convention d'équipe. Réponds en JSON : {\"rules\": [...]}."
)
PERSONAL_SUMMARY_SYSTEM = (
    "Tu résumes les habitudes de rangement d'une personne (ses papiers et fichiers personnels) à partir de ses "
    "corrections. Écris au plus 8 règles courtes, concrètes et vérifiables, en français, à la deuxième personne, "
    "qui disent dans quel dossier va quel genre de document (ex. « Tu ranges les factures du vétérinaire dans "
    "Animaux ») ou comment tu le décris (ex. « Tu gardes le nom de la personne dans la description »). Jamais de "
    "règle sur le format du nom (date, séparateurs, version, majuscules) : le nom est assemblé par le programme, pas "
    "par toi. N'invente rien. Réponds en JSON : {\"rules\": [...]}."
)


def summary_system(personal: bool) -> str:
    """Consigne de synthèse des règles selon le mode (Particulier : ni équipe ni dossiers d'agence)."""
    return PERSONAL_SUMMARY_SYSTEM if personal else SUMMARY_SYSTEM


def maybe_summarize(db: Database, llm: LLMProvider | None, every: int = SUMMARY_EVERY, force: bool = False,
                    personal: bool = False) -> bool:
    """Toutes les 5 corrections, régénère les règles lisibles. Renvoie True si les règles ont changé."""
    learnable = [c for c in list_corrections(db, 1000) if usable(c, personal)]
    bucket = len(learnable) // every
    if llm is None or (not force and (bucket == 0 or bucket <= (db.get_setting("rules_bucket", 0) or 0))):
        return False
    lines = [f"- « {c.original_name} » : l'IA proposait {c.ai_folder}/{c.ai_name} ; choix final "
             f"{c.final_folder}/{c.final_name} (modifié : {', '.join(f for f in c.changed_fields if ':' not in f)})"
             for c in learnable[:60]]
    current = [r.text for r in list_rules(db, kind="learned")]
    user = "Corrections récentes :\n" + "\n".join(lines)
    if current:
        user += "\n\nRègles actuelles (éventuellement modifiées par l'utilisateur, à conserver sauf contradiction) :\n" + \
                "\n".join(f"- {r}" for r in current)
    try:
        summary = llm.complete_json(summary_system(personal), user, RulesSummary)
    except LLMError as exc:
        log.warning("rules summary failed: %s", exc)
        return False
    replace_rules(db, summary.rules[:MAX_RULES], {"count": len(learnable), "corrections": lines[:10]})
    db.set_setting("rules_bucket", bucket)
    return True
