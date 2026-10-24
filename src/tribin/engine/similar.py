"""Fichiers « du même modèle de nom » déjà rangés : le signal le plus sûr pour les dossiers hors gabarit.

Ex. « 2026_03_likassi_regis_2026_03_25T08_57_09.pdf » et « 2026_07_likassi_regis_2026_07_28T13_45_02.pdf » (déjà dans
« salaire ») ont le même modèle une fois les chiffres remplacés : ce dossier est la destination la plus probable, même
s'il ne suit pas la convention client / année / projet.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tribin.config import ARCHIVE_DIRNAME, STAGING_DIRNAME
from tribin.convention.naming import split_extension
from tribin.fs.filters import ExclusionMatcher

MAX_FILES = 20000  # au-delà (très gros NAS), l'index s'arrête : le signal reste facultatif
MAX_DEPTH = 6
# Mots trop génériques pour qu'un nom soit reconnaissable (photos d'appareil, scans, documents sans titre…)
GENERIC = {"img", "dsc", "dcim", "pxl", "scan", "image", "photo", "document", "doc", "fichier", "file", "copie", "copy",
           "sans", "titre", "untitled", "nouveau", "new", "screenshot", "capture", "ecran", "final", "version",
           "telechargement", "download", "export", "pdf", "jpg", "png"}
_DIGITS = re.compile(r"\d+")
_SEPARATORS = re.compile(r"[\s_\-.()\[\]]+")
_WORDS = re.compile(r"[a-zà-ÿ]{3,}")


def name_pattern(name: str) -> str:
    """Modèle d'un nom : minuscules, chiffres -> « # », séparateurs unifiés (extension comprise)."""
    stem, ext = split_extension(name)
    return f"{_SEPARATORS.sub('_', _DIGITS.sub('#', stem.lower())).strip('_')}{ext.lower()}"


def distinctive_words(name: str) -> set[str]:
    return {w for w in _WORDS.findall(split_extension(name)[0].lower()) if w not in GENERIC}


@dataclass
class SimilarFolder:
    folder: str  # relatif à la racine
    count: int
    example: str

    def render(self) -> str:
        files = f"{self.count} fichier{'s' if self.count > 1 else ''}"
        return f"{self.folder} — {files} au nom du même modèle (ex. « {self.example} »)"


class PlacedFiles:
    """Index des fichiers déjà rangés dans une racine, par modèle de nom."""

    def __init__(self, root: Path, excluded: list[str] | None = None):
        self.root = Path(root)
        self.by_pattern: dict[str, list[tuple[str, str]]] = {}
        matcher = ExclusionMatcher(excluded or [])
        count = 0
        for current, dirs, files in os.walk(self.root):
            rel_dir = Path(current).relative_to(self.root).as_posix()
            rel_dir = "" if rel_dir == "." else rel_dir
            depth = rel_dir.count("/") + 1 if rel_dir else 0
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (STAGING_DIRNAME, ARCHIVE_DIRNAME)
                       and depth < MAX_DEPTH and not matcher.matches_rel(f"{rel_dir}/{d}" if rel_dir else d)]
            if not rel_dir:
                continue  # fichiers posés à la racine : pas un dossier de rangement
            for name in files:
                if name.startswith(".") or name.startswith("~$"):
                    continue
                self.by_pattern.setdefault(name_pattern(name), []).append((rel_dir, name))
                count += 1
                if count >= MAX_FILES:
                    return

    def similar(self, name: str, limit: int = 3) -> list[SimilarFolder]:
        """Dossiers contenant des fichiers du même modèle de nom (vide si le nom est trop générique)."""
        if len(distinctive_words(name)) < 1:
            return []
        matches = [m for m in self.by_pattern.get(name_pattern(name), []) if m[1] != name]
        counts = Counter(folder for folder, _ in matches)
        examples = {folder: file for folder, file in matches}
        return [SimilarFolder(folder, n, examples[folder]) for folder, n in counts.most_common(limit)]
