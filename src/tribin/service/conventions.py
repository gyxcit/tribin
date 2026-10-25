"""Création de la convention selon le mode d'utilisation : travail (agence) ou personnel."""

from __future__ import annotations

import shutil
from pathlib import Path

from tribin import resources
from tribin.config import ARCHIVE_DIRNAME, STAGING_DIRNAME
from tribin.convention.loader import Category, Convention, load_convention, save_convention
from tribin.convention.naming import strip_accents
from tribin.mapping.infer import infer_convention
from tribin.mapping.scanner import scan_root

MODES = {"work": "Travail", "personal": "Personnel"}
PERSONAL_TEMPLATE = Path(resources.__file__).with_name("convention.personal.yaml")
WORK_EXAMPLE = Path(resources.__file__).with_name("convention.example.yaml")
PERSONAL_FILE = "convention_personnel.yaml"


def _key(name: str) -> str:
    """« Salaires » et « salaire », « Santé » et « sante » : même catégorie."""
    key = strip_accents(name).casefold().strip()
    return key[:-1] if key.endswith("s") else key


def existing_top_folders(roots: list[str]) -> list[str]:
    """Dossiers de premier niveau déjà présents (hors dossiers internes et cachés)."""
    names: list[str] = []
    for root in roots:
        try:
            entries = sorted(Path(root).iterdir())
        except OSError:
            continue
        for entry in entries:
            if (entry.is_dir() and not entry.name.startswith((".", "~"))
                    and entry.name not in (STAGING_DIRNAME, ARCHIVE_DIRNAME) and entry.name not in names):
                names.append(entry.name)
    return names


def personal_convention(roots: list[str], base: Convention | None = None) -> Convention:
    """Convention personnelle : catégories types + dossiers déjà créés par l'utilisateur.

    Un dossier existant proche d'une catégorie type la remplace (« salaire » plutôt que « Salaires ») ; les autres
    deviennent de nouvelles catégories."""
    convention = base or load_convention(PERSONAL_TEMPLATE)
    categories = list(convention.structure.categories)
    for folder in existing_top_folders(roots):
        match = next((i for i, c in enumerate(categories) if _key(c.code) == _key(folder)), None)
        if match is not None:
            categories[match] = Category(code=folder, description=categories[match].description)
        else:
            categories.append(Category(code=folder, description="Dossier existant"))
    convention.structure.categories = categories
    return convention


def current_mode(service) -> str:
    """Mode de la convention configurée (« work » si aucune ou illisible)."""
    try:
        return "personal" if service.convention().personal else "work"
    except Exception:
        return "work"


def create_convention(mode: str, roots: list[str], data_dir: Path) -> tuple[Path, str]:
    """Crée la convention du mode choisi dans le dossier des données ; renvoie (chemin, message pour l'utilisateur)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    if mode == "personal":
        target = data_dir / PERSONAL_FILE
        base = load_convention(target) if target.exists() else None  # garde les catégories déjà créées
        save_convention(personal_convention(roots, base), target)
        return target, ("Mode personnel : vos fichiers sont rangés par catégorie puis par année. Si aucune catégorie "
                        "ne convient, TriBin en crée une.")
    target = data_dir / "convention.yaml"
    if target.exists():
        target = target.with_name(f"convention_{len(list(data_dir.glob('convention*.yaml'))) + 1}.yaml")
    profiles = [p for r in roots for p in scan_root(Path(r), Convention())]
    if any(p.file_count for p in profiles):
        save_convention(infer_convention(profiles), target)
        return target, ("Convention déduite de vos dossiers. Vous pouvez la relire et l'ajuster à tout moment "
                        f"(Réglages › Dossiers) : {target}")
    shutil.copy2(WORK_EXAMPLE, target)
    return target, ("Vos dossiers sont vides : TriBin part d'une convention type d'agence "
                    "(client / année / projet / catégorie), modifiable dans les réglages.")


def set_personal_depth(path: Path, depth: int) -> None:
    """Mode personnel : profondeur maximum (catégorie comprise) choisie dans les réglages."""
    convention = load_convention(path)
    convention.structure.max_depth = depth
    convention.structure.template = "{category}"
    save_convention(convention, path)


def date_prefix_template(template: str, separator: str, enabled: bool) -> str:
    """Gabarit de nommage avec ou sans la date en tête (« {date}_{description} » <-> « {description} »)."""
    if enabled:
        return template if "{date}" in template else "{date}" + separator + template
    for token in ("{date}" + separator, separator + "{date}", "{date}"):
        template = template.replace(token, "")
    return template


def has_date_prefix(convention: Convention) -> bool:
    return "{date}" in convention.naming.template


def set_date_prefix(path: Path, enabled: bool) -> None:
    """Réglages › Rangement : noms de fichiers avec ou sans la date au début."""
    convention = load_convention(path)
    convention.naming.template = date_prefix_template(convention.naming.template, convention.naming.separator, enabled)
    save_convention(convention, path)


def add_category(path: Path, code: str, description: str = "Créée automatiquement par TriBin") -> bool:
    """Ajoute une catégorie à la convention (mode personnel) ; faux si elle existait déjà."""
    convention = load_convention(path)
    if any(_key(c.code) == _key(code) for c in convention.structure.categories):
        return False
    convention.structure.categories.append(Category(code=code, description=description))
    save_convention(convention, path)
    return True
