"""Génère (ou régénère) le jeu d'essai du mode Particulier, au format d'un jeu de test (section 10 de SPEC.md).

    python scripts/make_sandbox_perso.py            # crée ./sandbox-perso/
    python scripts/make_sandbox_perso.py --dest DIR # ailleurs (tests)

Contenu : convention.yaml (convention personnelle + dossier « startup » de l'utilisateur), root/ (papiers déjà rangés),
inbox/ (27 fichiers à ranger), expected.csv (dossier attendu, dossiers acceptables, nom attendu, mot-clé du nom).
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

from sandbox_files import write_file  # noqa: E402
from sandbox_perso_data import EXISTING_FOLDERS, INBOX, ROOT_FILES  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
MARKER = ".tribin-sandbox"
PERSONAL_TEMPLATE = REPO_ROOT / "src" / "tribin" / "resources" / "convention.personal.yaml"


def build_convention() -> dict:
    """La convention personnelle de TriBin, telle que l'application la crée : catégories types ; « startup » est un
    dossier de l'utilisateur hors de la liste (le cas réel : créé après la convention)."""
    base = yaml.safe_load(PERSONAL_TEMPLATE.read_text(encoding="utf-8"))
    base["name"] = "Rangement particulier (jeu d'essai)"
    return base


def _clear(dest: Path) -> None:
    if not dest.exists():
        return
    if not (dest / MARKER).exists():
        if any(dest.iterdir()):
            raise SystemExit(f"Refus : {dest} existe, n'est pas vide et n'est pas une sandbox TriBin ({MARKER} absent).")
        return
    shutil.rmtree(dest)


def make_sandbox_perso(dest: Path) -> dict[str, int]:
    dest = dest.resolve()
    _clear(dest)
    root, inbox = dest / "root", dest / "inbox"
    root.mkdir(parents=True)
    inbox.mkdir(parents=True)
    (dest / MARKER).write_text("Jeu d'essai Particulier généré par scripts/make_sandbox_perso.py\n", encoding="utf-8")
    with open(dest / "convention.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_convention(), fh, allow_unicode=True, sort_keys=False)
    for name in EXISTING_FOLDERS:
        (root / name).mkdir(exist_ok=True)
    for rel, spec in ROOT_FILES:
        write_file(root / rel, spec)
    for name, spec, *_ in INBOX:
        write_file(inbox / name, spec)
    with open(dest / "expected.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "expected_folder", "expected_name", "acceptable_folders", "expected_keyword"])
        for name, _, folder, expected_name, acceptable, keyword in INBOX:
            writer.writerow([name, folder, expected_name, "|".join(acceptable), keyword])
    return {"root_files": len(ROOT_FILES), "inbox_files": len(INBOX), "folders": len(EXISTING_FOLDERS)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génère le jeu d'essai du mode Particulier.")
    parser.add_argument("--dest", type=Path, default=REPO_ROOT / "sandbox-perso",
                        help="dossier de destination (défaut : ./sandbox-perso)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stats = make_sandbox_perso(args.dest)
    print(f"Jeu d'essai créé dans {args.dest.resolve()} : {stats['folders']} dossiers, "
          f"{stats['root_files']} fichiers déjà rangés, {stats['inbox_files']} fichiers à ranger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
