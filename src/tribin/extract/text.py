"""Fichiers texte (notes, tableaux CSV, sous-titres, agendas, contacts, configuration, code) : 4 000 premiers
caractères, mots de passe et clés masqués avant l'envoi à l'IA."""

from __future__ import annotations

import re
from pathlib import Path

from tribin.models import FileInfo

MAX_CHARS = 4000
# « password = … », « "api_key": "…" », « TOKEN: … » : la valeur est remplacée, la clé reste (elle aide à classer)
_SECRET = re.compile(r"""(?im)^(\s*["']?[\w.-]*(?:pass(?:word|wd)?|pwd|mdp|mot[ _-]?de[ _-]?passe|secret|token|"""
                     r"""api[_-]?key|private[_-]?key|"""
                     r"""access[_-]?key|credential)s?[\w.-]*["']?\s*[:=]\s*)(.+)$""")
_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)


def redact_secrets(text: str) -> str:
    """Masque les valeurs qui ressemblent à des mots de passe, des jetons ou des clés privées."""
    text = _KEY_BLOCK.sub("[clé privée masquée]", text)
    return _SECRET.sub(lambda m: m.group(1) + "•••", text)


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
    info.text = redact_secrets(decode(raw))[:MAX_CHARS]
