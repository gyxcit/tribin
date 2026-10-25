"""Apprentissage à partir des corrections (section 6.7).

- chaque validation est enregistrée (proposition de l'IA, choix final, décision, champs modifiés) ;
- les corrections similaires servent d'exemples dans le prompt (5 au plus) ;
- une correction qui contredit la convention d'équipe n'est PAS apprise : elle est comptée et signalée si fréquente.
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from tribin.convention.loader import Convention
from tribin.convention.naming import split_extension, split_template
from tribin.convention.structure import fields_from_folder, matches_template
from tribin.engine.similar import distinctive_words
from tribin.db import Database
from tribin.models import FileInfo, Proposal

MAX_EXAMPLES = 5
MIN_NAME_SIMILARITY = 55  # en dessous, sans mot distinctif commun, une correction n'est pas un exemple
TEAM_RULE_ALERT = 3
LEARNABLE = ("edited", "alternative_chosen")


@dataclass
class Correction:
    id: int
    original_name: str
    extension: str
    client_hint: str | None
    ai_folder: str
    ai_name: str
    final_folder: str
    final_name: str
    decision: str
    changed_fields: list[str]
    contradicts_team: bool
    source: str


# --- conformité à la convention d'équipe ------------------------------------------------------

_DATE_PARTS = {"%Y": r"\d{4}", "%m": r"\d{2}", "%d": r"\d{2}", "%y": r"\d{2}"}


def _segment_regex(segment: str, convention: Convention) -> tuple[str, bool]:
    """Expression régulière d'un segment du gabarit ; booléen : segment obligatoire (description)."""
    naming = convention.naming
    sep = re.escape(naming.separator)
    out, required = [], False
    for literal, var, _, _ in string.Formatter().parse(segment):
        out.append(re.escape(literal))
        if var == "date":
            fmt = re.escape(naming.date_format)
            for code, rx in _DATE_PARTS.items():
                fmt = fmt.replace(re.escape(code), rx)
            out.append(fmt)
            required = True  # le code met toujours une date (à défaut, celle de modification du fichier)
        elif var == "client":
            codes = [re.escape(c.code) for c in convention.clients] or [r"[A-Za-z0-9]+"]
            out.append("(?:" + "|".join(codes) + ")")
        elif var == "version":
            out.append(r"\d+")
        elif var == "description":
            out.append(rf"(?:(?!{sep})\S)+")
            required = True
        elif var:
            out.append(rf"(?:(?!{sep})\S)+")
    return "".join(out), required


def name_conforms(name: str, convention: Convention) -> bool:
    """Le nom suit-il le gabarit de nommage (segments facultatifs, dans l'ordre) ?"""
    sep = convention.naming.separator
    stem = split_extension(name)[0]
    stem = re.sub(r"_\d+$", "", stem)  # suffixe de collision _2, _3…
    parts = []
    for segment in split_template(convention.naming.template, sep):
        rx, required = _segment_regex(segment, convention)
        group = f"{re.escape(sep)}{rx}"
        parts.append(group if required else f"(?:{group})?")
    return re.fullmatch("".join(parts), sep + stem, flags=re.IGNORECASE) is not None


def contradicts_team(final_folder: str, final_name: str, convention: Convention) -> list[str]:
    """Règles d'équipe que le choix final ne respecte pas."""
    broken = []
    if final_folder and not matches_template(final_folder, convention):
        broken.append("structure")
    if final_name and not name_conforms(final_name, convention):
        broken.append("nommage")
    return broken


def changed_fields(proposal: Proposal, final_folder: str, final_name: str, convention: Convention) -> list[str]:
    changed = []
    if final_folder != proposal.target_folder:
        changed.append("dossier")
        before, after = fields_from_folder(proposal.target_folder, convention), fields_from_folder(final_folder, convention)
        changed += [k for k in ("client", "project_code", "category") if before.get(k) != after.get(k)]
    if final_name != proposal.new_name:
        changed.append("nom")
    return changed


# --- enregistrement --------------------------------------------------------------------------


def record_correction(db: Database, convention: Convention, original_name: str, excerpt: str, client_hint: str | None,
                      proposal: Proposal, final_folder: str, final_name: str, decision: str,
                      source: str = "explicit") -> list[str]:
    """Enregistre une validation. Renvoie les règles d'équipe contredites (vide si conforme ; toujours vide en mode
    personnel : pas d'équipe, un dossier hors des catégories est un choix comme un autre)."""
    check_team = decision in LEARNABLE and not convention.personal
    broken = contradicts_team(final_folder, final_name, convention) if check_team else []
    with db.tx() as c:
        c.execute(
            "INSERT INTO corrections(ts, original_name, extension, excerpt, client_hint, ai_folder, ai_name, final_folder, "
            "final_name, decision, changed_fields, contradicts_team, source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), original_name, split_extension(original_name)[1].lower(),
             excerpt[:300], client_hint, proposal.target_folder, proposal.new_name, final_folder, final_name, decision,
             json.dumps(changed_fields(proposal, final_folder, final_name, convention) + [f"équipe:{b}" for b in broken]),
             int(bool(broken)), source),
        )
    return broken


def list_corrections(db: Database, limit: int = 500) -> list[Correction]:
    rows = db.query("SELECT * FROM corrections ORDER BY id DESC LIMIT ?", (limit,))
    return [Correction(r["id"], r["original_name"], r["extension"], r["client_hint"], r["ai_folder"] or "",
                       r["ai_name"] or "", r["final_folder"], r["final_name"], r["decision"],
                       json.loads(r["changed_fields"]), bool(r["contradicts_team"]), r["source"]) for r in rows]


def team_rule_alerts(db: Database) -> list[str]:
    """Règles d'équipe souvent corrigées (à remonter au référent)."""
    counts: dict[str, int] = {}
    for corr in list_corrections(db):
        for field_name in corr.changed_fields:
            if field_name.startswith("équipe:"):
                counts[field_name[7:]] = counts.get(field_name[7:], 0) + 1
    labels = {"structure": "structure des dossiers", "nommage": "nommage des fichiers"}
    return [f"Cette règle d'équipe est souvent corrigée : {labels.get(k, k)} ({n} fois)."
            for k, n in sorted(counts.items()) if n >= TEAM_RULE_ALERT]


# --- récupération des exemples ---------------------------------------------------------------


def usable(corr: Correction, personal: bool = False) -> bool:
    """Correction dont on peut apprendre. Celles qui contredisent la convention d'équipe sont écartées, sauf en mode
    personnel (y compris celles enregistrées avant que ce mode ne les accepte)."""
    return corr.decision in LEARNABLE and (personal or not corr.contradicts_team)


def similar_examples(db: Database, info: FileInfo, client_hint: str | None, limit: int = MAX_EXAMPLES,
                     personal: bool = False) -> list[str]:
    """Jusqu'à 5 corrections récentes dont le nom ressemble vraiment à celui-ci (similarité ≥ 55 ou mot distinctif
    commun) ; même extension et même client ne font que départager. Une correction sur un CV ne sert jamais
    d'exemple pour un relevé bancaire parce que les deux sont des PDF."""
    stem = split_extension(info.name)[0].lower()
    words = distinctive_words(info.name)
    scored = []
    for corr in list_corrections(db, 300):
        if not usable(corr, personal):
            continue
        name_score = fuzz.token_set_ratio(stem, split_extension(corr.original_name)[0].lower())
        shared = words & distinctive_words(corr.original_name)
        if name_score < MIN_NAME_SIMILARITY and not shared:
            continue
        score = name_score + 20 * bool(shared)
        score += 10 if corr.extension == info.extension else 0
        score += 10 if client_hint and corr.client_hint == client_hint else 0
        scored.append((score, -corr.id, corr))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [format_example(c) for _, _, c in scored[:limit]]


def format_example(c: Correction) -> str:
    client = f", client {c.client_hint}" if c.client_hint else ""
    return (f"« {c.original_name} » ({c.extension or 'sans extension'}{client}) → {c.final_folder}/{c.final_name} "
            f"(l'IA proposait {c.ai_folder}/{c.ai_name})")


def placed_path(root: Path, folder: str, name: str) -> Path:
    return Path(root).joinpath(*[p for p in folder.split("/") if p], name)
