"""Dossiers candidats proposés à l'IA."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from tribin.convention.loader import Convention
from tribin.convention.naming import split_extension
from tribin.convention.structure import matches_template
from tribin.engine.clients import normalize_text
from tribin.fs.filters import INTERNAL_DIRS, ExclusionMatcher, is_hidden, is_package
from tribin.mapping.profiles import FolderProfile
from tribin.models import FileInfo


@dataclass
class Candidate:
    rel: str  # chemin relatif à la racine, séparateur "/"
    description: str = ""

    def render(self) -> str:
        return f"{self.rel} — {self.description}" if self.description else self.rel


def walk_folders(root: Path, convention: Convention, max_depth: int = 4, limit: int | None = 200) -> list[str]:
    """Dossiers de la racine jusqu'à `max_depth`, hors zones exclues, dossiers internes, cachés et paquets."""
    matcher = ExclusionMatcher(convention.excluded_paths)
    root = Path(root)
    found: list[str] = []
    stack: list[tuple[Path, str, int]] = [(root, "", 0)]
    while stack:
        current, rel, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name.lower(), reverse=True)
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path)
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            if entry.name.lower() in INTERNAL_DIRS or is_hidden(path) or is_package(path):
                continue
            if matcher.matches_rel(child_rel):
                continue
            found.append(child_rel)
            stack.append((path, child_rel, depth + 1))
    found.sort(key=str.lower)
    return found[:limit] if limit else found


STOPWORDS = {"les", "des", "pour", "avec", "une", "dans", "sur", "par", "the", "and", "aux", "est", "pas", "fichier",
              "fichiers", "date", "total", "eur", "objet", "projet", "client"}
# Code projet « 2026-042 » : jamais le début d'une date (« 2026-10-12 » ne contient pas le code 2026-10)
PROJECT_CODE = re.compile(r"(?<!\d)(\d{4}-\d{2,4})(?!\d|-\d)")
RESERVED_FOR_OTHERS = 3
MAX_FREE_TOP_FOLDERS = 6  # dossiers de premier niveau hors catégories / clients (« startup ») toujours candidats
TREE_MAX_FOLDERS = 40
TREE_MAX_SUBFOLDERS = 8


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if len(t) >= 3 and t not in STOPWORDS}


def _folder_score(file_tokens: set[str], codes: set[str], profile: FolderProfile, convention: Convention) -> float:
    folder_tokens = _tokens(f"{profile.rel.replace('/', ' ')} {profile.description} {' '.join(profile.samples)}")
    score = 0.0
    for token in folder_tokens:
        if token in file_tokens:
            score += 10
        elif len(token) >= 5:
            match = process.extractOne(token, file_tokens, scorer=fuzz.ratio, score_cutoff=85)
            if match:
                score += 6
    segments = profile.rel.split("/")
    score += 40 * sum(1 for code in codes if any(seg == code or seg.startswith(f"{code}_") for seg in segments))
    if matches_template(profile.rel, convention):
        score += 5
    return score


def rangeable(profiles: list[FolderProfile]) -> list[FolderProfile]:
    """Retire les dossiers intermédiaires vides (ex. « ACME/2026 ») : ils occupent des places sans être des
    destinations de rangement. Un dossier vide sans sous-dossier reste candidat."""
    parents = {p.rel.rsplit("/", 1)[0] for p in profiles if "/" in p.rel}
    return [p for p in profiles if p.file_count or p.rel not in parents]


def project_folders(profiles: list[FolderProfile], convention: Convention, limit: int = 60) -> list[str]:
    """Dossiers projet existants (niveau {project} du gabarit), pour que l'IA puisse construire un chemin."""
    levels = convention.structure.template.split("/")
    if "{project}" not in levels:
        return []
    depth = levels.index("{project}") + 1
    return sorted((p.rel for p in profiles if p.rel.count("/") + 1 == depth), key=str.lower)[:limit]


def is_free_top_folder(rel: str, convention: Convention) -> bool:
    """Mode Particulier : dossier de premier niveau créé par l'utilisateur hors des catégories (« startup »).
    Toujours candidat : il vaut une catégorie. (En Professionnel, un dossier libre à la racine n'est qu'un parent
    de sous-dossiers, visibles dans l'arborescence et candidats s'ils ressemblent au fichier.)"""
    return convention.personal and "/" not in rel and convention.find_category(rel) is None


def _diversified(profiles: list[FolderProfile]) -> list[FolderProfile]:
    """Dossiers à égalité (score nul) : un par dossier de premier niveau d'abord, les plus récents en tête, plutôt
    que les quinze premiers de l'alphabet."""
    groups: dict[str, list[FolderProfile]] = {}
    for p in profiles:
        groups.setdefault(p.rel.split("/")[0].lower(), []).append(p)
    for members in groups.values():
        members.sort(key=lambda p: (-(p.last_modified or 0), p.rel.lower()))
    ordered: list[FolderProfile] = []
    queues = sorted(groups.values(), key=lambda m: (-(m[0].last_modified or 0), m[0].rel.lower()))
    while queues:
        for members in list(queues):
            ordered.append(members.pop(0))
            if not members:
                queues.remove(members)
    return ordered


def select_candidates(info: FileInfo, profiles: list[FolderProfile], convention: Convention,
                      client_code: str | None, limit: int = 15) -> list[Candidate]:
    """Les `limit` dossiers les plus pertinents ; ceux du client détecté sont toujours inclus en priorité, ainsi que
    les dossiers de premier niveau hors structure (« startup »). À score nul, un dossier par premier niveau."""
    file_tokens = _tokens(f"{split_extension(info.name)[0]} {info.text[:2000]} {' '.join(info.metadata.values())}")
    codes = set(PROJECT_CODE.findall(f"{info.name} {info.text}"))
    free = [p for p in profiles if is_free_top_folder(p.rel, convention)][:MAX_FREE_TOP_FOLDERS]
    profiles = rangeable(profiles)
    scored = [(_folder_score(file_tokens, codes, p, convention), p) for p in profiles]
    scored.sort(key=lambda sp: (-sp[0], sp[1].rel.lower()))
    ranked = [p for s, p in scored if s > 0] + _diversified([p for s, p in scored if s <= 0])
    prefix = f"{client_code.lower()}/" if client_code else None
    mine = [p for p in ranked if prefix and (p.rel.lower() + "/").startswith(prefix)]
    mine_ids = {id(p) for p in mine}
    others = [p for p in ranked if id(p) not in mine_ids]
    chosen = mine[: max(0, limit - RESERVED_FOR_OTHERS)] if others else mine[:limit]
    chosen += others[: limit - len(chosen)]
    seen = {p.rel.lower() for p in chosen}
    missing = [p for p in free if p.rel.lower() not in seen]
    if missing:  # les dossiers libres prennent la place des candidats les moins pertinents (fin de liste)
        chosen = chosen[: max(0, limit - len(missing))] + missing
    return [Candidate(p.rel, p.description or p.auto_description()) for p in sorted(chosen, key=lambda p: p.rel.lower())]


def folder_tree(profiles: list[FolderProfile], max_folders: int = TREE_MAX_FOLDERS,
                max_subfolders: int = TREE_MAX_SUBFOLDERS) -> list[str]:
    """Arborescence de premier niveau pour l'IA : « Etudes — 7 — Attestations, CV, … », « Sante — 0 — (vide) ».

    Le nombre de fichiers compte les sous-dossiers ; l'IA voit ainsi ce qui existe ET ce qui n'existe pas (un dossier
    parent vide reste visible même s'il n'est pas candidat)."""
    tops = sorted((p for p in profiles if "/" not in p.rel), key=lambda p: p.rel.lower())
    lines = []
    for top in tops[:max_folders]:
        prefix = f"{top.rel}/"
        inside = [p for p in profiles if p.rel.startswith(prefix)]
        total = top.file_count + sum(p.file_count for p in inside)
        subs = sorted((p.rel[len(prefix):] for p in inside if "/" not in p.rel[len(prefix):]), key=str.lower)
        line = f"{top.rel} — {total}"
        if subs:
            shown = ", ".join(subs[:max_subfolders])
            line += f" — {shown}" + (f", … ({len(subs)} sous-dossiers)" if len(subs) > max_subfolders else "")
        elif not total:
            line += " — (vide)"
        lines.append(line)
    if len(tops) > max_folders:
        lines.append(f"… et {len(tops) - max_folders} autres dossiers")
    return lines


def phase1_candidates(root: Path, convention: Convention) -> list[Candidate]:
    """Phase 1 : tous les dossiers jusqu'à une profondeur de 4 (200 au plus), les plus profonds en priorité."""
    folders = walk_folders(root, convention, max_depth=4, limit=None)
    folders.sort(key=lambda r: (-r.count("/"), r.lower()))
    return [Candidate(rel) for rel in sorted(folders[:200], key=str.lower)]
