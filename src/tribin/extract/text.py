"""Fichiers texte (.txt, .md, .csv) : 4 000 premiers caractères."""

from __future__ import annotations

from pathlib import Path

from tribin.models import FileInfo

MAX_CHARS = 4000


def decode(raw: bytes) -> str:
    """Décode en UTF-8, sinon en Windows-1252 (fichiers Excel/Windows), sans jamais échouer."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def extract_text(path: Path, info: FileInfo) -> None:
    with open(path, "rb") as fh:
        raw = fh.read(MAX_CHARS * 4)
    info.text = decode(raw)[:MAX_CHARS]
