"""Chemins de dossiers à partir du gabarit de structure de la convention."""

from __future__ import annotations

import re
import string
from datetime import date

from tribin.convention.loader import Convention
from tribin.convention.naming import clean_segment
from tribin.models import NameFields


def project_folder_name(fields: NameFields, convention: Convention) -> str:
    """Nom du dossier projet (ex. « 2026-042_Campagne-Noel »), vide si les éléments manquent."""
    naming = convention.naming
    values = {
        "project_code": clean_segment(fields.project_code or "", naming),
        "project_name": clean_segment(fields.project_name or "", naming),
    }
    fmt = convention.structure.project_format
    needed = {name for _, name, _, _ in string.Formatter().parse(fmt) if name}
    if any(not values.get(n) for n in needed):
        return ""
    return fmt.format(**values)


def folder_from_fields(fields: NameFields, convention: Convention, fallback_date: date | None = None) -> str:
    """Chemin relatif construit avec le gabarit de structure, ou "" si un élément manque."""
    year_source = fields.date or fallback_date
    project_code = fields.project_code or ""
    year = project_code[:4] if project_code[:4].isdigit() else (str(year_source.year) if year_source else "")
    values = {
        "client": (fields.client or "").upper(),
        "year": year,
        "project": project_folder_name(fields, convention),
        "category": fields.category or "",
    }
    needed = {name for _, name, _, _ in string.Formatter().parse(convention.structure.template) if name}
    if any(not values[n] for n in needed):  # seulement les éléments du gabarit (mode personnel : catégorie, année)
        return ""
    return convention.structure.template.format(**values)


def _project_regex(convention: Convention) -> re.Pattern[str]:
    fmt = convention.structure.project_format
    out = []
    for literal, name, _, _ in string.Formatter().parse(fmt):
        out.append(re.escape(literal))
        if name == "project_code":
            out.append(r"(?P<project_code>\d{4}-\d{2,4}|[^_/]+?)")
        elif name:
            out.append(rf"(?P<{name}>.+)")
    return re.compile("^" + "".join(out) + "$")


def fields_from_folder(rel_folder: str, convention: Convention) -> dict[str, str]:
    """Lit client, année, projet et catégorie dans un chemin conforme au gabarit (ce qui est reconnaissable)."""
    parts = [p for p in rel_folder.replace("\\", "/").split("/") if p]
    template_parts = convention.structure.template.split("/")
    found: dict[str, str] = {}
    for part, tpl in zip(parts, template_parts):
        if tpl == "{client}":
            client = convention.client_by_code(part)
            if client:
                found["client"] = client.code
        elif tpl == "{year}" and part.isdigit():
            found["year"] = part
        elif tpl == "{category}" and part in convention.category_codes():
            found["category"] = part
        elif tpl == "{project}":
            match = _project_regex(convention).match(part)
            if match:
                found.update({k: v for k, v in match.groupdict().items() if v})
    return found


def matches_template(rel_folder: str, convention: Convention) -> bool:
    """Vrai si le chemin relatif a la profondeur du gabarit et que la catégorie (dernier niveau) est connue."""
    parts = [p for p in rel_folder.replace("\\", "/").split("/") if p]
    template_parts = convention.structure.template.split("/")
    if len(parts) != len(template_parts):
        return False
    for part, tpl in zip(parts, template_parts):
        if tpl == "{category}" and part not in convention.category_codes():
            return False
        if tpl == "{client}" and convention.clients and not convention.client_by_code(part):
            return False
    return True
