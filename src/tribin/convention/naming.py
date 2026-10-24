"""Construction et nettoyage des noms de fichiers (section 6.4). Le nom est construit par le code, jamais par l'IA."""

from __future__ import annotations

import re
import string
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tribin.convention.loader import Naming
    from tribin.models import NameFields

COMPOUND_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")
FORBIDDEN_CHARS = '<>:"/\\|?*'
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_PATH_LENGTH = 250
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_VERSION_PATTERNS = [
    re.compile(r"(?:^|[_\-\s.])v(?:ersion)?[_\-\s]?(\d{1,3})(?=$|[_\-\s.(])", re.IGNORECASE),
    re.compile(r"[_\-\s](\d{1,2})$"),
]


def split_extension(name: str) -> tuple[str, str]:
    """Sépare le nom et l'extension ; conserve les extensions composées (.tar.gz)."""
    low = name.lower()
    for ext in COMPOUND_EXTENSIONS:
        if low.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)], name[-len(ext):]
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:  # pas d'extension, fichier « .caché » ou point final
        return name, ""
    ext = name[dot:]
    if " " in ext or len(ext) > 12:  # « Rapport v1.final draft » n'a pas d'extension
        return name, ""
    return name[:dot], ext


def strip_accents(text: str) -> str:
    """Retire les accents (NFKD) et tout caractère non ASCII (emojis…)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.encode("ascii", "ignore").decode("ascii")


def clean_segment(text: str, naming: Naming) -> str:
    """Nettoie un morceau de nom : accents, caractères interdits, espaces -> séparateur de mots."""
    text = unicodedata.normalize("NFC", str(text))
    if naming.ascii_only:
        text = strip_accents(text)
    text = _CONTROL.sub("", text)
    text = "".join(" " if ch in FORBIDDEN_CHARS else ch for ch in text)
    ws = naming.word_separator
    # Le séparateur de segments est réservé : à l'intérieur d'un segment il devient séparateur de mots.
    if naming.separator and naming.separator != ws:
        text = text.replace(naming.separator, " ")
    text = re.sub(r"\s+", " ", text).strip()
    if ws:
        text = text.replace(" ", ws)
        text = re.sub(re.escape(ws) + "{2,}", ws, text).strip(ws)
    return text.strip(" .")


def extract_version(original_name: str) -> int | None:
    """Version présente dans un nom d'origine (v2, V02, _v3, -3…), normalisée en entier."""
    stem, _ = split_extension(original_name)
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(stem)
        if match:
            value = int(match.group(1))
            return value if value > 0 else None
    return None


def _render_value(name: str, fields: NameFields, naming: Naming, fallback_date: date | None) -> str:
    if name == "date":
        d = fields.date or fallback_date
        return d.strftime(naming.date_format) if d else ""
    if name == "year":
        d = fields.date or fallback_date
        return str(d.year) if d else ""
    if name == "version":
        return naming.version_format.format(fields.version) if fields.version else ""
    value = getattr(fields, name, None)
    return clean_segment(value, naming) if value else ""


def split_template(template: str, separator: str) -> list[str]:
    """Découpe le gabarit selon le séparateur, sans couper à l'intérieur des {variables}."""
    if not separator:
        return [template]
    segments, current, depth, i = [], [], 0, 0
    while i < len(template):
        ch = template[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if depth == 0 and template.startswith(separator, i):
            segments.append("".join(current))
            current = []
            i += len(separator)
            continue
        current.append(ch)
        i += 1
    segments.append("".join(current))
    return segments


def _assemble(fields: NameFields, naming: Naming, fallback_date: date | None, description: str | None) -> str:
    """Applique le gabarit ; un segment dont une variable est vide est retiré entièrement."""
    if description is not None:
        fields = fields.model_copy(update={"description": description})
    parts: list[str] = []
    for segment in split_template(naming.template, naming.separator):
        rendered, empty = [], False
        for literal, var, spec, _ in string.Formatter().parse(segment):
            rendered.append(literal)
            if var is None:
                continue
            value = _render_value(var, fields, naming, fallback_date)
            if not value:
                empty = True
                break
            rendered.append(format(value, spec) if spec else value)
        text = "".join(rendered)
        if not empty and text.strip():
            parts.append(text)
    return naming.separator.join(parts)


def _finalize_stem(stem: str, naming: Naming) -> str:
    stem = stem.rstrip(" .")
    if not stem:
        stem = "fichier"
    if stem.split(".")[0].upper() in WINDOWS_RESERVED:
        stem = f"{stem}{naming.word_separator or '_'}fichier"
    return stem


def normalize_extension(extension: str, naming: Naming) -> str:
    ext = extension.strip()
    if ext and not ext.startswith("."):
        ext = "." + ext
    ext = _CONTROL.sub("", "".join(ch for ch in ext if ch not in FORBIDDEN_CHARS))
    return ext.lower() if naming.lowercase_extension else ext


def build_name(fields: NameFields, naming: Naming, extension: str, fallback_date: date | datetime | None = None,
               max_length: int | None = None) -> str:
    """Construit le nom conforme à la convention.

    `fallback_date` : date de modification du fichier, utilisée si aucune date n'a été trouvée.
    `max_length` : longueur maximale du nom complet (par défaut celle de la convention).
    """
    if isinstance(fallback_date, datetime):
        fallback_date = fallback_date.date()
    ext = normalize_extension(extension, naming)
    limit = min(max_length or naming.max_length, naming.max_length)
    description = clean_segment(fields.description, naming) if fields.description else ""
    stem = _assemble(fields, naming, fallback_date, description)
    budget = limit - len(ext)
    if len(stem) > budget and description:
        # Tronquer d'abord la description.
        overflow = len(stem) - budget
        keep = max(0, len(description) - overflow)
        short = description[:keep].rstrip(naming.word_separator + " .")
        stem = _assemble(fields, naming, fallback_date, short)
    if len(stem) > budget:
        stem = stem[:max(1, budget)]
        stem = stem.rstrip(naming.separator + naming.word_separator)
    return _finalize_stem(stem, naming) + ext


def fit_to_path(fields: NameFields, naming: Naming, extension: str, folder: Path,
                fallback_date: date | datetime | None = None, limit: int = MAX_PATH_LENGTH) -> tuple[str, list[str]]:
    """Construit le nom en respectant la longueur maximale du chemin complet (Windows : ~260 caractères).

    Renvoie le nom et d'éventuels avertissements pour l'utilisateur.
    """
    warnings: list[str] = []
    name = build_name(fields, naming, extension, fallback_date)
    folder_len = len(str(folder)) + 1
    if folder_len + len(name) <= limit:
        return name, warnings
    available = limit - folder_len
    if available >= 20:
        shorter = build_name(fields, naming, extension, fallback_date, max_length=available)
        if folder_len + len(shorter) <= limit:
            warnings.append("Nom raccourci : le chemin complet dépassait la limite de Windows.")
            return shorter, warnings
    warnings.append("Chemin trop long pour Windows (plus de 250 caractères) : choisis un dossier moins profond.")
    return name, warnings


def unique_name(name: str, existing: set[str] | list[str]) -> str:
    """Ajoute _2, _3… si le nom existe déjà (comparaison insensible à la casse et à la forme Unicode)."""
    taken = {unicodedata.normalize("NFC", n).casefold() for n in existing}
    if unicodedata.normalize("NFC", name).casefold() not in taken:
        return name
    stem, ext = split_extension(name)
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{ext}"
        if unicodedata.normalize("NFC", candidate).casefold() not in taken:
            return candidate
        counter += 1


def is_valid_name(name: str) -> bool:
    """Vérifie qu'un nom (saisi par l'utilisateur, par exemple) est utilisable sur macOS et Windows."""
    if not name or name in {".", ".."} or name != name.rstrip(" ."):
        return False
    if any(ch in FORBIDDEN_CHARS for ch in name) or _CONTROL.search(name):
        return False
    stem = split_extension(name)[0]
    return stem.split(".")[0].upper() not in WINDOWS_RESERVED
