"""Parcours de l'arborescence existante (section 6.6) : un profil par dossier, sans jamais entrer dans les zones exclues."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from tribin.convention.loader import Convention
from tribin.convention.naming import split_extension
from tribin.fs.filters import INTERNAL_DIRS, ExclusionMatcher, is_hidden, is_ignored_name, is_package
from tribin.mapping.profiles import FolderProfile, detect_patterns

MAX_SAMPLES = 5
DEFAULT_DEPTH = 6

# Point d'injection pour les tests : liste les entrées d'un dossier.
ScanDir = Callable[[Path], list[os.DirEntry]]


def _scandir(path: Path) -> list[os.DirEntry]:
    with os.scandir(path) as it:
        return list(it)


def scan_root(root: Path, convention: Convention, max_depth: int = DEFAULT_DEPTH,
              scandir: ScanDir = _scandir, extra_excluded: list[str] | None = None) -> list[FolderProfile]:
    """Profils de tous les dossiers de la racine jusqu'à `max_depth` niveaux."""
    root = Path(root)
    matcher = ExclusionMatcher([*convention.excluded_paths, *(extra_excluded or [])])
    profiles: list[FolderProfile] = []
    stack: list[tuple[Path, str, int]] = [(root, "", 0)]
    while stack:
        current, rel, depth = stack.pop()
        try:
            entries = scandir(current)
        except OSError:
            continue
        names: list[str] = []
        exts: Counter[str] = Counter()
        latest = 0.0
        for entry in entries:
            path = Path(entry.path)
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            if entry.is_symlink() or is_hidden(path):
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name.lower() in INTERNAL_DIRS or is_package(path) or matcher.matches_rel(child_rel):
                    continue
                if depth + 1 <= max_depth:
                    stack.append((path, child_rel, depth + 1))
                continue
            if is_ignored_name(entry.name):
                continue
            names.append(entry.name)
            ext = split_extension(entry.name)[1].lower() or "(aucune)"
            exts[ext] += 1
            try:
                latest = max(latest, entry.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
        if rel:
            names.sort(key=str.lower)
            profiles.append(FolderProfile(
                rel=rel, file_count=len(names), extensions=[e for e, _ in exts.most_common(5)],
                samples=names[:MAX_SAMPLES], last_modified=latest or None, patterns=detect_patterns(names),
            ))
    profiles.sort(key=lambda p: p.rel.lower())
    return profiles
