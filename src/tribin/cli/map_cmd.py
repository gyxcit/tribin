"""Commandes map, import-clients et init-structure (phase 2)."""

from __future__ import annotations

import argparse
import csv
import shutil
import time
from pathlib import Path

from rich.table import Table
from rich.tree import Tree

from tribin.cli.common import CliError, console, load_convention_or_fail
from tribin.config import get_settings
from tribin.convention.loader import Client, Convention, save_convention
from tribin.convention.naming import unique_name
from tribin.db import Database
from tribin.engine.context import read_profile
from tribin.llm import make_provider
from tribin.llm.base import LLMError
from tribin.mapping.infer import infer_convention, propose_structure, structure_to_convention
from tribin.mapping.profiles import describe_profiles, load_profiles, save_profiles
from tribin.mapping.scanner import scan_root


def _free_path(path: Path) -> Path:
    """Chemin libre à côté de `path` (jamais d'écrasement)."""
    if not path.exists():
        return path
    existing = {p.name for p in path.parent.iterdir()}
    return path.with_name(unique_name(path.name, existing))


def backup(path: Path) -> Path:
    """Copie de sauvegarde avant de modifier un fichier de convention."""
    target = _free_path(path.with_name(path.name + ".bak"))
    shutil.copy2(path, target)
    return target


def cmd_map(args: argparse.Namespace) -> int:
    root: Path = args.root
    if not root.is_dir():
        raise CliError(f"Racine introuvable : {root}")
    convention = load_convention_or_fail(args.convention) if args.convention else Convention()
    settings = get_settings()
    db = Database(settings.db_path)
    started = time.monotonic()
    profiles = scan_root(root, convention, max_depth=args.depth)
    elapsed = time.monotonic() - started
    old = {p.rel: p.description for p in load_profiles(db, root)}
    for p in profiles:
        p.description = old.get(p.rel, "")
    if args.describe:
        try:
            llm = make_provider(settings, args.model)
        except LLMError as exc:
            raise CliError(str(exc)) from exc
        with console.status("Description des dossiers par l'IA (lots de 30)…"):
            n = describe_profiles(profiles, llm, only_missing=not args.redescribe)
        console.print(f"{n} dossier(s) décrit(s).")
    save_profiles(db, root, profiles)
    table = Table(title=f"Cartographie de {root} — {len(profiles)} dossiers en {elapsed:.1f} s")
    for col, kw in (("Dossier", {}), ("Fichiers", {"justify": "right"}), ("Extensions", {}), ("Motifs", {}),
                    ("Description", {})):
        table.add_column(col, **kw)
    for p in profiles:
        patterns = ", ".join(f"{k}={v}" for k, v in p.patterns.items())
        table.add_row(p.rel, str(p.file_count), " ".join(p.extensions[:3]), patterns, p.description or "[dim]—[/dim]")
    console.print(table)
    if args.suggest_convention:
        out = _free_path(args.suggest_convention)
        save_convention(infer_convention(profiles), out)
        console.print(f"Convention déduite de l'existant écrite dans {out} : relis-la et corrige-la avant de l'utiliser.")
    return 0


def read_clients_csv(path: Path) -> list[Client]:
    """CSV avec les colonnes code, nom (ou name) et alias (séparés par « | » ou « ; »)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample else csv.excel
        rows = list(csv.DictReader(fh, dialect=dialect))
    clients = []
    for row in rows:
        low = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        code = low.get("code", "")
        if not code:
            continue
        aliases = [a.strip() for a in low.get("alias", low.get("aliases", "")).replace(";", "|").split("|") if a.strip()]
        clients.append(Client(code=code.upper(), name=low.get("nom", low.get("name", "")), aliases=aliases))
    return clients


def cmd_import_clients(args: argparse.Namespace) -> int:
    convention = load_convention_or_fail(args.convention)
    try:
        incoming = read_clients_csv(args.csv)
    except (OSError, csv.Error) as exc:
        raise CliError(f"CSV illisible : {exc}") from exc
    added, skipped = [], []
    for client in incoming:
        if convention.client_by_code(client.code):
            skipped.append(client.code)
        else:
            convention.clients.append(client)
            added.append(client.code)
    if added:
        saved = backup(args.convention)
        save_convention(convention, args.convention)
        console.print(f"{len(added)} client(s) ajouté(s) : {', '.join(added)} (sauvegarde : {saved.name})")
    else:
        console.print("Aucun nouveau client à ajouter.")
    if skipped:
        console.print(f"[dim]Déjà présents : {', '.join(skipped)}[/dim]")
    return 0


def structure_tree(convention: Convention) -> Tree:
    tree = Tree(f"[bold]{convention.structure.template}[/bold]")
    example = convention.structure.template.format(client="CLIENT", year="2026",
                                                   project=convention.structure.project_format.format(
                                                       project_code="2026-001", project_name="Projet"),
                                                   category="{catégorie}")
    branch = tree.add(f"[dim]exemple : {example}[/dim]")
    for c in convention.structure.categories:
        branch.add(f"{c.code} — {c.description}")
    return tree


def cmd_init_structure(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        llm = make_provider(settings, args.model)
    except LLMError as exc:
        raise CliError(str(exc)) from exc
    samples = sorted(p.name for p in args.samples.iterdir() if p.is_file()) if args.samples else None
    with console.status("L'IA propose une structure…"):
        proposed = propose_structure(read_profile(settings), llm, samples)
    base = load_convention_or_fail(args.base) if args.base else None
    convention = structure_to_convention(proposed, base)
    console.print(structure_tree(convention))
    if proposed.explanation:
        console.print(f"[dim]{proposed.explanation}[/dim]")
    if not args.yes and input("Écrire cette convention ? [o/N] ").strip().lower() not in {"o", "oui", "y", "yes"}:
        console.print("Rien n'a été écrit.")
        return 0
    out = _free_path(args.output)
    save_convention(convention, out)
    console.print(f"Convention écrite dans {out}. Tu peux la modifier (renommer, ajouter ou retirer des catégories) "
                  "avant de créer les dossiers avec « tribin create-structure ».")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("map", help="cartographier une racine existante")
    p.add_argument("root", type=Path)
    p.add_argument("--convention", type=Path, help="pour respecter les zones exclues")
    p.add_argument("--depth", type=int, default=6)
    p.add_argument("--describe", action="store_true", help="générer les descriptions des dossiers avec l'IA")
    p.add_argument("--redescribe", action="store_true", help="régénérer toutes les descriptions")
    p.add_argument("--suggest-convention", type=Path, metavar="YAML", help="écrire une convention déduite de l'existant")
    p.add_argument("--model")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("import-clients", help="ajouter des clients à la convention depuis un CSV")
    p.add_argument("csv", type=Path)
    p.add_argument("--convention", type=Path, required=True)
    p.set_defaults(func=cmd_import_clients)

    p = sub.add_parser("init-structure", help="proposer une structure de zéro et écrire la convention")
    p.add_argument("--output", type=Path, default=Path("convention.yaml"))
    p.add_argument("--base", type=Path, help="convention existante à compléter (nommage, clients)")
    p.add_argument("--samples", type=Path, help="dossier d'exemples de fichiers")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--model")
    p.set_defaults(func=cmd_init_structure)
