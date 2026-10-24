"""Fichiers à ne jamais traiter (section 3.2) et zones exclues (motifs glob relatifs à la racine)."""

from __future__ import annotations

import os
import re
import stat
import sys
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
IGNORED_SUFFIXES = (".tmp", ".part", ".crdownload", ".tribin-partial")
# Paquets macOS : des dossiers qui ressemblent à des fichiers.
PACKAGE_SUFFIXES = (".app", ".fcpbundle", ".fcpxbundle", ".photoslibrary", ".band", ".logicx",
                    ".imovielibrary", ".aplibrary", ".rtfd", ".bundle", ".framework", ".plugin")
# Dossiers internes à TriBin, toujours exclus de la cartographie.
INTERNAL_DIRS = {"_tribin", "_archive", "_versions"}

EXCLUDED_ZONE_MESSAGE = ("Ce fichier est dans un dossier projet protégé : le déplacer peut casser des liens "
                         "dans InDesign, After Effects ou Premiere")


class NotProcessable(ValueError):
    """Fichier refusé ; le message est destiné à l'utilisateur (en français)."""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def is_hidden(path: Path) -> bool:
    """Caché sous macOS (nom en « . ») ou sous Windows (attribut caché ou système)."""
    if path.name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))
        except (OSError, AttributeError):
            return False
    return False


def is_package(path: Path) -> bool:
    return path.suffix.lower() in PACKAGE_SUFFIXES


def is_ignored_name(name: str) -> bool:
    """Fichiers système ou temporaires (.DS_Store, ~$*, *.tmp, *.tribin-partial…)."""
    low = name.lower()
    return low in IGNORED_NAMES or low.startswith("~$") or low.endswith(IGNORED_SUFFIXES)


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    pat = pattern.replace("\\", "/").strip("/")
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("(?:/.*)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


class ExclusionMatcher:
    """Teste si un chemin (relatif à une racine) tombe dans une zone exclue."""

    def __init__(self, patterns: list[str]):
        self.patterns = [p for p in patterns if p.strip()]

    def matches_rel(self, rel: str) -> bool:
        rel = nfc(rel.replace("\\", "/").strip("/"))
        if not rel:
            return False
        return any(_glob_regex(nfc(p)).match(rel) for p in self.patterns)

    def is_excluded(self, path: Path, root: Path) -> bool:
        try:
            rel = Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root)))
        except ValueError:
            return False
        return self.matches_rel(rel.as_posix())


def check_processable(path: Path, root: Path | None = None, matcher: ExclusionMatcher | None = None) -> None:
    """Lève NotProcessable avec un message clair si le fichier ne doit pas être traité."""
    path = Path(path)
    if path.is_symlink():
        raise NotProcessable(f"« {path.name} » est un lien symbolique : TriBin ne traite que des fichiers réels.")
    if not path.exists():
        raise NotProcessable(f"« {path.name} » est introuvable.")
    if path.is_dir():
        if is_package(path):
            raise NotProcessable(f"« {path.name} » est un paquet (application ou bibliothèque) : TriBin ne range que des fichiers.")
        raise NotProcessable(f"« {path.name} » est un dossier : TriBin ne range que des fichiers.")
    if is_ignored_name(path.name):
        raise NotProcessable(f"« {path.name} » est un fichier système ou temporaire : il est ignoré.")
    if root is not None and matcher is not None and matcher.is_excluded(path, root):
        raise NotProcessable(EXCLUDED_ZONE_MESSAGE)


def is_being_written(path: Path, delay: float = 2.0) -> bool:
    """Vrai si la taille du fichier change pendant `delay` secondes (fichier en cours d'écriture)."""
    try:
        before = path.stat().st_size
        time.sleep(delay)
        return path.stat().st_size != before
    except OSError:
        return True
