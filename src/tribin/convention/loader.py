"""Lecture et validation du fichier de convention YAML (section 6.1), avec des erreurs lisibles."""

from __future__ import annotations

import string
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

STRUCTURE_VARS = {"client", "year", "project", "category"}
NAMING_VARS = {"date", "client", "project_code", "project_name", "description", "version", "category", "year"}


def template_vars(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class Category(BaseModel):
    code: str
    description: str = ""


class Structure(BaseModel):
    template: str = "{client}/{year}/{project}/{category}"
    project_format: str = "{project_code}_{project_name}"
    categories: list[Category] = Field(default_factory=list)

    @field_validator("template")
    @classmethod
    def _check_template(cls, v: str) -> str:
        unknown = template_vars(v) - STRUCTURE_VARS
        if unknown:
            raise ValueError(f"variables inconnues {sorted(unknown)} ; variables possibles : {sorted(STRUCTURE_VARS)}")
        return v


class Naming(BaseModel):
    template: str = "{date}_{client}_{project_code}_{description}_v{version}"
    separator: str = "_"
    word_separator: str = "-"
    date_format: str = "%Y-%m-%d"
    version_format: str = "{:02d}"
    ascii_only: bool = True
    max_length: int = Field(default=120, ge=20, le=250)
    lowercase_extension: bool = True
    versioned_categories: list[str] = Field(default_factory=list)

    @field_validator("template")
    @classmethod
    def _check_template(cls, v: str) -> str:
        unknown = template_vars(v) - NAMING_VARS
        if unknown:
            raise ValueError(f"variables inconnues {sorted(unknown)} ; variables possibles : {sorted(NAMING_VARS)}")
        if "description" not in template_vars(v):
            raise ValueError("le gabarit doit contenir {description}")
        return v

    @field_validator("version_format")
    @classmethod
    def _check_version_format(cls, v: str) -> str:
        try:
            v.format(1)
        except (IndexError, ValueError, KeyError) as exc:
            raise ValueError(f"format invalide ({exc}) ; exemple attendu : \"{{:02d}}\"") from exc
        return v


class Client(BaseModel):
    code: str
    name: str = ""
    aliases: list[str] = Field(default_factory=list)


class VersionsConfig(BaseModel):
    keep_older_in_subfolder: bool = True
    subfolder_name: str = "_versions"


class Convention(BaseModel):
    version: int = 1
    name: str = "Convention"
    language: str = "fr"
    structure: Structure = Field(default_factory=Structure)
    naming: Naming = Field(default_factory=Naming)
    clients: list[Client] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    versions: VersionsConfig = Field(default_factory=VersionsConfig)

    @model_validator(mode="after")
    def _unique_codes(self) -> Convention:
        seen: set[str] = set()
        for client in self.clients:
            key = client.code.upper()
            if key in seen:
                raise ValueError(f"code client en double : {client.code}")
            seen.add(key)
        return self

    def category_codes(self) -> list[str]:
        return [c.code for c in self.structure.categories]

    def client_by_code(self, code: str | None) -> Client | None:
        if not code:
            return None
        return next((c for c in self.clients if c.code.upper() == code.upper()), None)


class ConventionError(ValueError):
    """Convention invalide ; `problems` liste des messages lisibles (champ, problème, suggestion)."""

    def __init__(self, path: Path | None, problems: list[str]):
        self.problems = problems
        where = f" ({path})" if path else ""
        super().__init__(f"Fichier de convention invalide{where} :\n" + "\n".join(f"  - {p}" for p in problems))


_SUGGESTIONS = {
    "missing": "ajoute ce champ",
    "string_type": "mets le texte entre guillemets",
    "int_parsing": "indique un nombre entier",
    "bool_parsing": "indique true ou false",
    "list_type": "indique une liste (lignes commençant par « - »)",
}


def _readable(exc: ValidationError) -> list[str]:
    problems = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "(racine)"
        msg = err["msg"].removeprefix("Value error, ")
        hint = _SUGGESTIONS.get(err["type"])
        problems.append(f"champ « {field} » : {msg}" + (f" — suggestion : {hint}" if hint else ""))
    return problems


def parse_convention(data: dict, path: Path | None = None) -> Convention:
    try:
        return Convention.model_validate(data or {})
    except ValidationError as exc:
        raise ConventionError(path, _readable(exc)) from exc


def load_convention(path: Path) -> Convention:
    """Charge et valide un fichier de convention. Lève ConventionError avec des messages en français."""
    path = Path(path)
    if not path.exists():
        raise ConventionError(path, ["fichier introuvable — suggestion : vérifie le chemin dans les réglages"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"ligne {mark.line + 1}, colonne {mark.column + 1}" if mark else "position inconnue"
        raise ConventionError(path, [f"YAML illisible ({where}) — suggestion : vérifie l'indentation et les guillemets"]) from exc
    if not isinstance(data, dict):
        raise ConventionError(path, ["le fichier doit contenir des champs (version, structure, naming…)"])
    return parse_convention(data, path)


def save_convention(convention: Convention, path: Path) -> None:
    """Écrit la convention en YAML lisible (utilisé par import-clients et init-structure)."""
    data = convention.model_dump(mode="json")
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
