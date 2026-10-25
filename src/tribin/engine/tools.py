"""Outils que l'IA peut appeler pendant une proposition (skill v2, § 2.4 et 2.4 bis).

Un registre générique (`Tool`), un budget commun par fichier (`ToolSession`, 3 appels tous outils confondus) et, pour
cette version, un seul outil : `lister_dossiers`, qui lit l'arborescence à la demande à partir des profils de dossiers
déjà en mémoire. Un outil suivant (`lire_plus`, `chercher_ranges`) s'ajoute ici sans toucher au prompt : une
déclaration, une fonction, une ligne dans la feuille de route du skill.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tribin.fs.filters import INTERNAL_DIRS, ExclusionMatcher, is_hidden, is_ignored_name, is_package
from tribin.llm.base import MAX_TOOL_CALLS
from tribin.mapping.profiles import FolderProfile

MAX_FOLDERS_PER_ANSWER = 60
EXAMPLES_PER_FOLDER = 3
EXAMPLES_FOR_REQUESTED = 5
BUDGET_MESSAGE = "budget épuisé : décide avec ce que tu sais"
FOLDER_TOOL = "lister_dossiers"


@dataclass
class Tool:
    """Un outil : sa déclaration (identique chez les trois fournisseurs, traduite dans leur format) et sa fonction."""

    name: str
    description: str
    input_schema: dict
    call: Callable[[dict], dict]  # arguments -> réponse, sérialisée en JSON pour le modèle

    @property
    def declaration(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


class ToolSession:
    """Les outils d'une proposition et leur budget commun ; journalise chaque appel (`Proposal.tool_calls`).

    Au-delà du budget, l'outil répond « budget épuisé » (l'appel est noté `refuse`) ; le fournisseur cesse alors de
    proposer les outils (`tool_choice = none`)."""

    def __init__(self, tools: list[Tool], max_calls: int = MAX_TOOL_CALLS):
        self.tools = {t.name: t for t in tools}
        self.max_calls = max_calls
        self.calls: list[dict] = []

    @property
    def declarations(self) -> list[dict]:
        return [t.declaration for t in self.tools.values()]

    @property
    def exhausted(self) -> bool:
        return sum(1 for c in self.calls if not c.get("refuse")) >= self.max_calls

    def __call__(self, name: str, arguments: dict | None) -> str:
        arguments = dict(arguments or {})
        if self.exhausted:
            self.calls.append({"outil": name, "arguments": arguments, "refuse": True})
            return json.dumps({"erreur": BUDGET_MESSAGE}, ensure_ascii=False)
        self.calls.append({"outil": name, "arguments": arguments})
        tool = self.tools.get(name)
        if tool is None:
            return json.dumps({"erreur": f"Outil inconnu : {name}"}, ensure_ascii=False)
        try:
            result = tool.call(arguments)
        except Exception as exc:  # jamais de plantage : l'IA reçoit une erreur lisible
            result = {"erreur": f"L'outil a échoué ({type(exc).__name__})."}
        return json.dumps(result, ensure_ascii=False)


def looked_at(calls: list[dict]) -> list[str]:
    """Les dossiers que l'IA a regardés (« racine », « Etudes »…), dans l'ordre, sans doublon ni appel refusé."""
    seen: list[str] = []
    for call in calls:
        if call.get("refuse") or call.get("outil") != FOLDER_TOOL:
            continue
        label = str(call.get("arguments", {}).get("chemin") or "").strip().strip("/") or "racine"
        if label not in seen:
            seen.append(label)
    return seen


# --- lister_dossiers --------------------------------------------------------------------------------------

FOLDER_TOOL_DESCRIPTION = (
    "Liste les sous-dossiers d'un dossier de la racine de rangement, avec le nombre de fichiers et quelques noms de "
    "fichiers en exemple. Appelle-le avec \"\" pour la racine. À utiliser pour vérifier qu'un dossier existe avant d'en "
    "proposer un nouveau, pour voir les sous-dossiers d'une catégorie, ou quand aucun candidat ne traite du même sujet "
    "que le fichier."
)
FOLDER_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "chemin": {"type": "string", "description": "Chemin relatif à la racine, séparateur « / ». \"\" = la racine."},
        "profondeur": {"type": "integer", "minimum": 1, "maximum": 2, "default": 1,
                       "description": "1 = les sous-dossiers directs ; 2 = et leurs propres sous-dossiers."},
    },
    "required": ["chemin"],
}


def _normalize(chemin) -> str | None:
    """Chemin relatif propre, « » pour la racine ; None s'il sort de la racine (absolu, « .. »)."""
    text = str(chemin or "").strip().replace("\\", "/")
    if text in ("", ".", "/", "./"):
        return ""
    if text.startswith("/") or (len(text) > 1 and text[1] == ":") or text.startswith("~"):
        return None
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _scan(root: Path, rel: str) -> list[FolderProfile] | None:
    """Repli quand un dossier n'est pas dans les profils (créé après la cartographie) : lecture directe du disque,
    limitée au dossier demandé et à ses sous-dossiers directs."""
    base = root / rel if rel else root
    if not base.is_dir():
        return None

    def profile(path: Path, as_rel: str) -> FolderProfile:
        names, subs = [], 0
        try:
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False):
                    if not entry.name.startswith(".") and entry.name.lower() not in INTERNAL_DIRS:
                        subs += 1
                elif not is_ignored_name(entry.name):
                    names.append(entry.name)
        except OSError:
            pass
        names.sort(key=str.lower)
        return FolderProfile(rel=as_rel, file_count=len(names), samples=names[:EXAMPLES_FOR_REQUESTED],
                             patterns={"sous_dossiers": str(subs)})

    found = [profile(base, rel)] if rel else []
    try:
        for entry in sorted(os.scandir(base), key=lambda e: e.name.lower()):
            if (entry.is_dir(follow_symlinks=False) and not entry.name.startswith(".")
                    and entry.name.lower() not in INTERNAL_DIRS and not is_hidden(Path(entry.path))
                    and not is_package(Path(entry.path))):
                child_rel = f"{rel}/{entry.name}" if rel else entry.name
                found.append(profile(Path(entry.path), child_rel))
    except OSError:
        pass
    return found


def folder_lister(root: Path, profiles: list[FolderProfile] | None = None, excluded: list[str] | None = None) -> Tool:
    """L'outil `lister_dossiers`, bâti sur les profils de la cartographie (réponse instantanée, pas de parcours du
    disque) ; `os.scandir` seulement pour un dossier absent des profils."""
    root = Path(root)
    matcher = ExclusionMatcher(excluded or [])
    by_rel: dict[str, FolderProfile] = {p.rel: p for p in profiles or []}

    def children_of(rel: str, source: dict[str, FolderProfile]) -> list[FolderProfile]:
        prefix = f"{rel}/" if rel else ""
        return sorted((p for r, p in source.items() if r.startswith(prefix) and "/" not in r[len(prefix):]
                       and r != rel and not matcher.matches_rel(r)), key=lambda p: p.rel.lower())

    def entry(p: FolderProfile, source: dict[str, FolderProfile], examples: int) -> dict:
        subs = p.patterns.get("sous_dossiers")
        return {"nom": p.rel.rsplit("/", 1)[-1], "fichiers": p.file_count,
                "sous_dossiers": int(subs) if subs is not None else len(children_of(p.rel, source)),
                "exemples": list(p.samples[:examples])}

    def call(arguments: dict) -> dict:
        rel = _normalize(arguments.get("chemin"))
        if rel is None:
            return {"erreur": "Chemin refusé : indique un chemin relatif à la racine, sans « .. » (\"\" pour la racine)."}
        head = rel.split("/")[0].lower() if rel else ""
        if head in INTERNAL_DIRS or head.startswith(".") or (rel and matcher.matches_rel(rel)):
            return {"erreur": f"Dossier hors du rangement : {rel}", "suggestion": "appelle lister_dossiers(\"\") pour voir la racine"}
        try:
            depth = max(1, min(2, int(arguments.get("profondeur") or 1)))
        except (TypeError, ValueError):
            depth = 1
        source = by_rel
        if rel and rel not in source:
            match = next((r for r in source if r.lower() == rel.lower()), None)  # casse différente
            if match:
                rel = match
            else:
                scanned = _scan(root, rel)
                if scanned is None:
                    return {"erreur": f"Dossier introuvable : {rel}", "suggestion": "appelle lister_dossiers(\"\") pour voir la racine"}
                source = {p.rel: p for p in scanned}
        elif not rel and not source:
            source = {p.rel: p for p in _scan(root, "") or []}
        here = source.get(rel) if rel else None
        answer: dict = {"chemin": rel, "fichiers_ici": here.file_count if here else 0,
                        "exemples": list(here.samples[:EXAMPLES_FOR_REQUESTED]) if here else [], "dossiers": [],
                        "tronque": False}
        budget = MAX_FOLDERS_PER_ANSWER
        for child in children_of(rel, source):
            if budget <= 0:
                answer["tronque"] = True
                answer["precision"] = "précise le chemin pour voir la suite"
                break
            item = entry(child, source, EXAMPLES_PER_FOLDER)
            budget -= 1
            if depth == 2:
                item["dossiers"] = []
                for grand in children_of(child.rel, source):
                    if budget <= 0:
                        answer["tronque"] = True
                        answer["precision"] = "précise le chemin pour voir la suite"
                        break
                    item["dossiers"].append(entry(grand, source, EXAMPLES_PER_FOLDER))
                    budget -= 1
            answer["dossiers"].append(item)
        return answer

    return Tool(FOLDER_TOOL, FOLDER_TOOL_DESCRIPTION, FOLDER_TOOL_SCHEMA, call)


def default_tools(root: Path, profiles: list[FolderProfile] | None, excluded: list[str] | None) -> list[Tool]:
    """Les outils enregistrés pour cette version : `lister_dossiers` seulement."""
    return [folder_lister(root, profiles, excluded)]
