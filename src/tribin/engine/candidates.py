"""Dossiers candidats proposés à l'IA."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tribin.convention.loader import Convention
from tribin.fs.filters import INTERNAL_DIRS, ExclusionMatcher, is_hidden, is_package


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


def phase1_candidates(root: Path, convention: Convention) -> list[Candidate]:
    """Phase 1 : tous les dossiers jusqu'à une profondeur de 4 (200 au plus), les plus profonds en priorité."""
    folders = walk_folders(root, convention, max_depth=4, limit=None)
    folders.sort(key=lambda r: (-r.count("/"), r.lower()))
    return [Candidate(rel) for rel in sorted(folders[:200], key=str.lower)]
