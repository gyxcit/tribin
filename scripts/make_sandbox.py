"""Génère (ou régénère) la sandbox de développement au format d'un jeu de test (section 10 de SPEC.md).

    python scripts/make_sandbox.py            # crée ./sandbox/
    python scripts/make_sandbox.py --dest DIR # crée la sandbox ailleurs (tests)

Contenu : convention.yaml, root/ (agence fictive déjà rangée), inbox/ (fichiers à ranger), expected.csv.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from sandbox_data import CATEGORIES, CLIENTS, EXCLUDED_FILES, INBOX, PROJECTS, ROOT_FILES  # noqa: E402
from sandbox_files import write_file  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
MARKER = ".tribin-sandbox"


def build_convention() -> dict:
    """Convention de la sandbox : celle de convention.example.yaml, avec la liste complète des clients."""
    base = yaml.safe_load((REPO_ROOT / "convention.example.yaml").read_text(encoding="utf-8"))
    base["name"] = "Convention Agence Exemple (sandbox)"
    base["clients"] = CLIENTS
    return base


def _clear(dest: Path) -> None:
    """Vide la sandbox existante, uniquement si elle porte le marqueur (jamais un autre dossier)."""
    if not dest.exists():
        return
    if not (dest / MARKER).exists():
        if any(dest.iterdir()):
            raise SystemExit(f"Refus : {dest} existe, n'est pas vide et n'est pas une sandbox TriBin ({MARKER} absent).")
        return
    shutil.rmtree(dest)


def _root_specs() -> list[tuple[str, dict]]:
    names = {c["code"]: c["name"] for c in CLIENTS}
    specs: list[tuple[str, dict]] = []
    for client, year, code, pname, label in PROJECTS:
        project_dir = f"{client}/{year}/{code}_{pname}"
        for cat in CATEGORIES:
            for date, desc, version, ext in ROOT_FILES[code].get(cat, []):
                name = f"{date}_{client}_{code}_{desc}" + (f"_v{version:02d}" if version else "") + ext
                lines = [names[client], label, desc.replace("-", " "), f"Projet {code}", date]
                kind = "pdf" if ext == ".pdf" else "image"
                specs.append((f"{project_dir}/{cat}/{name}", {"kind": kind, "lines": lines, "mtime": date}))
    specs.extend(EXCLUDED_FILES)
    return specs


def make_sandbox(dest: Path) -> dict[str, int]:
    """Crée la sandbox dans `dest` et renvoie quelques compteurs."""
    dest = dest.resolve()
    _clear(dest)
    root, inbox = dest / "root", dest / "inbox"
    root.mkdir(parents=True)
    inbox.mkdir(parents=True)
    (dest / MARKER).write_text("Sandbox TriBin générée par scripts/make_sandbox.py\n", encoding="utf-8")

    with open(dest / "convention.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_convention(), fh, allow_unicode=True, sort_keys=False)

    for client, year, code, pname, _ in PROJECTS:
        for cat in CATEGORIES:
            (root / client / year / f"{code}_{pname}" / cat).mkdir(parents=True, exist_ok=True)
    root_specs = _root_specs()
    for rel, spec in root_specs:
        write_file(root / rel, spec)

    for name, spec, *_ in INBOX:
        write_file(inbox / name, spec)

    with open(dest / "expected.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "expected_folder", "expected_name", "acceptable_folders"])
        for name, _, folder, expected_name, acceptable in INBOX:
            writer.writerow([name, folder, expected_name, "|".join(acceptable)])

    return {"root_files": len(root_specs), "inbox_files": len(INBOX), "projects": len(PROJECTS)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génère la sandbox de développement TriBin.")
    parser.add_argument("--dest", type=Path, default=REPO_ROOT / "sandbox", help="dossier de destination (défaut : ./sandbox)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stats = make_sandbox(args.dest)
    print(f"Sandbox créée dans {args.dest.resolve()} : {stats['projects']} projets, "
          f"{stats['root_files']} fichiers déjà rangés, {stats['inbox_files']} fichiers à ranger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
