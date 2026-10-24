"""Convention déduite de l'existant (quand aucune n'existe) et structure proposée « de zéro » par l'IA."""

from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field

from tribin.convention.loader import Category, Client, Convention, Naming, Structure
from tribin.convention.naming import strip_accents
from tribin.llm.base import LLMProvider
from tribin.mapping.profiles import FolderProfile

YEAR = re.compile(r"^(19|20)\d{2}$")
PROJECT = re.compile(r"^\d{4}[-_]\d{2,4}[-_ ].+")
DATE_TO_STRFTIME = {"AAAA-MM-JJ": "%Y-%m-%d", "AAAAMMJJ": "%Y%m%d", "JJ-MM-AAAA": "%d-%m-%Y", "AAAA_MM_JJ": "%Y_%m_%d"}


def _client_code(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", strip_accents(name)).upper()
    return letters[:8] or "CLIENT"


def infer_convention(profiles: list[FolderProfile], name: str = "Convention déduite de l'existant") -> Convention:
    """Déduit structure et nommage dominants. Le résultat est un brouillon que l'utilisateur relit et valide."""
    by_level: dict[int, Counter[str]] = {}
    for p in profiles:
        parts = p.rel.split("/")
        for level, part in enumerate(parts):
            by_level.setdefault(level, Counter())[part] += 1
    leaf_depths = Counter(len(p.rel.split("/")) for p in profiles if p.file_count)
    depth = leaf_depths.most_common(1)[0][0] if leaf_depths else 1
    roles: list[str] = []
    for level in range(depth):
        names = by_level.get(level, Counter())
        if level == 0:
            roles.append("{client}")
        elif names and sum(1 for n in names if YEAR.match(n)) >= len(names) / 2:
            roles.append("{year}")
        elif names and sum(1 for n in names if PROJECT.match(n)) >= len(names) / 2:
            roles.append("{project}")
        elif level == depth - 1:
            roles.append("{category}")
        else:
            roles.append("{project}")
    if "{category}" not in roles:
        roles.append("{category}")
    category_level = roles.index("{category}")
    category_names = by_level.get(category_level, Counter())
    categories = [Category(code=n, description="") for n, c in sorted(category_names.items()) if c >= 2] or \
        [Category(code=n) for n in sorted(category_names)]
    # Clients : dossiers de premier niveau qui suivent la structure dominante (« Administratif », « personnel »…,
    # moins profonds, sont des dossiers libres et non des clients).
    structured = {p.rel.split("/")[0] for p in profiles if len(p.rel.split("/")) >= depth}
    top = sorted(n for n in by_level.get(0, Counter()) if n in structured) or sorted(by_level.get(0, Counter()))
    clients = [Client(code=_client_code(n), name=n, aliases=[n.lower()]) for n in top]
    seen, unique_clients = set(), []
    for c in clients:
        if c.code not in seen:
            seen.add(c.code)
            unique_clients.append(c)

    patterns = Counter()
    separators = Counter()
    for p in profiles:
        if p.patterns.get("date_format"):
            patterns[(p.patterns["date_format"], p.patterns.get("date_position", "début"))] += p.file_count
        if p.patterns.get("separator") in {"_", "-", "."}:
            separators[p.patterns["separator"]] += p.file_count
    naming = Naming()
    if separators:
        naming.separator = separators.most_common(1)[0][0]
        naming.word_separator = "-" if naming.separator != "-" else "_"
    if patterns:
        (fmt, position), _ = patterns.most_common(1)[0]
        naming.date_format = DATE_TO_STRFTIME.get(fmt, "%Y-%m-%d")
        sep = naming.separator
        if position == "fin":
            naming.template = sep.join(["{client}", "{project_code}", "{description}", "v{version}", "{date}"])
        else:
            naming.template = sep.join(["{date}", "{client}", "{project_code}", "{description}", "v{version}"])
    else:
        naming.template = naming.separator.join(["{date}", "{client}", "{project_code}", "{description}", "v{version}"])
    return Convention(name=name, structure=Structure(template="/".join(roles), categories=categories),
                      naming=naming, clients=unique_clients)


# --- créer de zéro ---------------------------------------------------------------------------


class ProposedCategory(BaseModel):
    code: str
    description: str


class ProposedStructure(BaseModel):
    template: str = "{client}/{year}/{project}/{category}"
    project_format: str = "{project_code}_{project_name}"
    categories: list[ProposedCategory] = Field(default_factory=list)
    explanation: str = ""


CREATE_SYSTEM = (
    "Tu conçois l'arborescence de rangement d'une agence ou d'un studio. Propose une structure simple et durable : "
    "un gabarit de chemin utilisant uniquement les variables {client}, {year}, {project}, {category}, un format de "
    "dossier projet utilisant {project_code} et {project_name}, et 4 à 8 catégories numérotées (ex. « 01_Brief ») "
    "avec une description d'une phrase. Réponds uniquement en JSON."
)


def propose_structure(profile: str, llm: LLMProvider, sample_names: list[str] | None = None) -> ProposedStructure:
    user = f"Profil de l'utilisateur :\n{profile or '(non renseigné)'}\n"
    if sample_names:
        user += "\nExemples de fichiers à ranger :\n" + "\n".join(f"- {n}" for n in sample_names[:40])
    user += ('\n\nRéponds avec {"template": "...", "project_format": "...", '
             '"categories": [{"code": "01_...", "description": "..."}], "explanation": "..."}')
    return llm.complete_json(CREATE_SYSTEM, user, ProposedStructure)


def structure_to_convention(proposed: ProposedStructure, base: Convention | None = None) -> Convention:
    base = base or Convention(name="Convention de l'équipe")
    data = base.model_dump()
    data["structure"] = {
        "template": proposed.template, "project_format": proposed.project_format,
        "categories": [{"code": c.code, "description": c.description} for c in proposed.categories],
    }
    return Convention.model_validate(data)
