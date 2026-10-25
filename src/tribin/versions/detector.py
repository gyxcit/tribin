"""Détection des versions (section 6.9) : séries v1 / v2 / final, numéro suivant, anciennes versions dans _versions/."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from tribin.convention.loader import Convention
from tribin.convention.naming import extract_version, fit_to_path, split_extension, split_template, strip_accents, unique_name
from tribin.fs.filters import is_hidden, is_ignored_name
from tribin.models import FileInfo, Proposal

if TYPE_CHECKING:
    from tribin.engine.proposer import ProposeContext

log = logging.getLogger(__name__)

SIMILARITY = 85
PHASH_DISTANCE = 10
FAMILIES = [
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".gif", ".bmp"},
    {".psd", ".psb"}, {".ai", ".eps", ".svg"}, {".pdf"}, {".indd", ".idml"}, {".doc", ".docx", ".odt", ".rtf"},
    {".xls", ".xlsx", ".xlsm", ".ods", ".csv"}, {".ppt", ".pptx", ".key", ".odp"}, {".mp4", ".mov", ".avi", ".mkv"},
]
IMAGE_FAMILY = FAMILIES[0]
STATUS_TOKENS = r"v(?:ersion)?\s?\d{1,3}|final(?:e|_?ok)?|def(?:initif|initive)?|ok|valide|validee?|copie|copy|bis"
_TOKEN = re.compile(rf"(?:^|(?<=[\s_\-.]))(?:{STATUS_TOKENS})(?=$|[\s_\-.(])", re.IGNORECASE)
_DATES = re.compile(r"(?<!\d)(?:\d{4}[-_.]?\d{2}[-_.]?\d{2}|\d{2}[-_.]\d{2}[-_.]\d{4})(?!\d)")
_COPY_NUMBER = re.compile(r"\(\d+\)|[-_\s]\d{1,2}$")


def family(ext: str) -> frozenset[str]:
    ext = ext.lower()
    return frozenset(next((f for f in FAMILIES if ext in f), {ext}))


def normalize_base(name: str) -> str:
    """Nom de base : sans jetons de version et de statut, dates, casse, accents ni séparateurs."""
    stem = split_extension(name)[0]
    stem = strip_accents(stem).lower()
    stem = _DATES.sub(" ", stem)
    previous = None
    while previous != stem:
        previous = stem
        stem = _COPY_NUMBER.sub(" ", stem).strip(" _-.")
        stem = _TOKEN.sub(" ", stem).strip(" _-.")
    return re.sub(r"[^a-z0-9]+", "", stem)


def description_of(name: str, convention: Convention) -> str | None:
    """Description d'un nom conforme au gabarit d'équipe (ex. « Affiche-Noel »), sinon None."""
    sep = convention.naming.separator
    parts = split_extension(name)[0].split(sep)
    segments = split_template(convention.naming.template, sep)
    if "{description}" not in segments or len(parts) < 2:
        return None
    clients = {c.code.upper() for c in convention.clients}
    kept = [p for p in parts if not _DATES.fullmatch(p) and p.upper() not in clients
            and not re.fullmatch(r"\d{4}-\d{2,4}|v\d+|\d{1,2}", p, re.IGNORECASE)]
    return sep.join(kept) if kept else None


def _bases(name: str, convention: Convention) -> set[str]:
    bases = {normalize_base(name)}
    desc = description_of(name, convention)
    if desc:
        bases.add(normalize_base(desc))
    return {b for b in bases if len(b) >= 3}


def _similar(a: set[str], b: set[str]) -> bool:
    return any(x == y or fuzz.ratio(x, y) >= SIMILARITY for x in a for y in b)


def _phash(path: Path):
    try:
        import imagehash
        from PIL import Image

        with Image.open(path) as img:
            return imagehash.phash(img)
    except Exception:
        return None


@dataclass
class VersionMatch:
    path: Path
    version: int
    in_target: bool


def find_versions(info: FileInfo, proposal: Proposal, target: Path, convention: Convention) -> list[VersionMatch]:
    """Fichiers du dossier cible (et du dossier d'origine, plus anciens) qui sont des versions du même document."""
    me = Path(info.path)
    my_bases = _bases(info.name, convention) | {normalize_base(proposal.fields.description)} - {""}
    my_family = family(info.extension)
    my_hash = _phash(me) if info.extension in IMAGE_FAMILY else None
    matches: list[VersionMatch] = []
    for folder, in_target in ((target, True), (me.parent, False)):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if not entry.is_file(follow_symlinks=False) or path == me or is_ignored_name(entry.name) or is_hidden(path):
                continue
            if family(split_extension(entry.name)[1]) != my_family or not _similar(my_bases, _bases(entry.name, convention)):
                continue
            if not in_target and entry.stat().st_mtime >= me.stat().st_mtime:
                continue  # dans le dossier d'origine, seules les versions plus anciennes comptent
            if my_hash is not None:
                other = _phash(path)
                if other is not None and my_hash - other > PHASH_DISTANCE:
                    continue
            matches.append(VersionMatch(path, extract_version(entry.name) or 1, in_target))
    return matches


def apply_versioning(info: FileInfo, proposal: Proposal, ctx: ProposeContext) -> None:
    """Complète la proposition : numéro de version suivant et anciennes versions à ranger dans _versions/."""
    conv = ctx.convention
    if proposal.fields.category not in conv.naming.versioned_categories:
        return
    target = Path(ctx.root).joinpath(*[p for p in proposal.target_folder.split("/") if p])
    matches = find_versions(info, proposal, target, conv)
    own = extract_version(info.name)
    if matches:
        version = max(max(m.version for m in matches) + 1, own or 0)
        base = proposal.fields.description or split_extension(info.name)[0]
        proposal.warnings.append(f"Nouvelle version de {base.replace(' ', '-')} → v{conv.naming.version_format.format(version)}")
        if conv.versions.keep_older_in_subfolder:
            proposal.older_versions = [str(m.path) for m in matches if m.in_target]
    else:
        version = own or 1
    if version == proposal.fields.version:
        return
    proposal.fields.version = version
    from tribin.engine.proposer import date_fallback

    name, _ = fit_to_path(proposal.fields, conv.naming, info.extension, target,
                          fallback_date=date_fallback(proposal.document_date_source, info))
    existing = {e.name for e in os.scandir(target)} if target.is_dir() else set()
    proposal.new_name = unique_name(name, existing)
