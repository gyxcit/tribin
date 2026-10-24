"""Commandes propose, propose-dir et eval (phase 1 : aucun déplacement de fichier)."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.table import Table

from tribin.cli.common import CliError, console, load_convention_or_fail, print_proposal, proposals_table
from tribin.config import REPO_ROOT, get_settings
from tribin.engine.context import make_context
from tribin.engine.proposer import ProposeContext, propose
from tribin.extract import extract
from tribin.fs.filters import ExclusionMatcher, NotProcessable, check_processable
from tribin.llm import make_provider
from tribin.llm.base import LLMError


def _context(root: Path, convention_path: Path, model: str | None) -> ProposeContext:
    if not root.is_dir():
        raise CliError(f"Racine introuvable : {root}")
    settings = get_settings()
    convention = load_convention_or_fail(convention_path)
    try:
        llm = make_provider(settings, model)
    except LLMError as exc:
        raise CliError(str(exc)) from exc
    return make_context(root, convention, llm, settings)


def cmd_propose(args: argparse.Namespace) -> int:
    ctx = _context(args.root, args.convention, args.model)
    try:
        check_processable(args.file, ctx.root, ExclusionMatcher(ctx.convention.excluded_paths))
    except NotProcessable as exc:
        raise CliError(str(exc)) from exc
    with console.status("Analyse du fichier…"):
        proposal = propose(extract(args.file), ctx)
    if args.json:
        print(json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print_proposal(args.file.name, proposal)
    return 0


def cmd_propose_dir(args: argparse.Namespace) -> int:
    ctx = _context(args.root, args.convention, args.model)
    matcher = ExclusionMatcher(ctx.convention.excluded_paths)
    files, skipped = [], []
    for path in sorted(args.folder.iterdir(), key=lambda p: p.name.lower()):
        try:
            check_processable(path, ctx.root, matcher)
            files.append(path)
        except NotProcessable as exc:
            skipped.append((path.name, str(exc)))
    with console.status(f"Analyse de {len(files)} fichiers…"), ThreadPoolExecutor(max_workers=4) as pool:
        proposals = list(pool.map(lambda p: propose(extract(p), ctx), files))
    console.print(proposals_table([(f.name, p) for f, p in zip(files, proposals)]))
    for name, reason in skipped:
        console.print(f"[dim]Ignoré : {name} — {reason}[/dim]")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from tribin.eval.evaluate import run_eval, save_report

    settings = get_settings()
    testset = args.testset
    if not (testset / "expected.csv").exists():
        raise CliError(f"Jeu de test invalide : {testset / 'expected.csv'} introuvable.")
    try:
        llm = make_provider(settings, args.model)
    except LLMError as exc:
        raise CliError(str(exc)) from exc
    with console.status("Évaluation en cours (aucun fichier n'est déplacé)…"):
        report = run_eval(testset, lambda root, conv: make_context(root, conv, llm, settings))
    table = Table(title=f"Évaluation — {report.model} — prompt {report.prompt_version}")
    table.add_column("Indicateur")
    table.add_column("Valeur", justify="right")
    labels = {
        "fichiers": "Fichiers", "dossiers_exacts_pct": "Dossiers exacts (%)",
        "dossiers_acceptables_pct": "Dossiers acceptables (%)", "clients_corrects_pct": "Clients corrects (%)",
        "categories_correctes_pct": "Catégories correctes (%)", "noms_exacts_pct": "Noms exacts (%)",
        "confiance_bonnes": "Confiance moyenne (bonnes)", "confiance_mauvaises": "Confiance moyenne (mauvaises)",
        "temps_moyen_s": "Temps moyen par fichier (s)", "cout_moyen_usd": "Coût estimé par fichier ($)",
        "a_traiter_manuellement": "À traiter manuellement",
    }
    for key, value in report.metrics.items():
        table.add_row(labels.get(key, key), "—" if value == -1 else str(value))
    console.print(table)
    errors = [r for r in report.rows if not r.folder_ok]
    if errors and args.verbose:
        detail = Table(title="Dossiers incorrects")
        for col in ("Fichier", "Attendu", "Proposé"):
            detail.add_column(col)
        for r in errors:
            detail.add_row(r.file, r.expected_folder, r.proposal.target_folder if r.proposal else r.error)
        console.print(detail)
    path = save_report(report, REPO_ROOT / "eval_results")
    console.print(f"Rapport enregistré : {path}")
    score = report.metrics["dossiers_acceptables_pct"]
    if args.min_score is not None and score < args.min_score:
        console.print(f"[red]Objectif non atteint : {score} % de dossiers corrects (minimum {args.min_score} %).[/red]")
        return 2
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("propose", help="proposer un rangement pour un fichier (sans le déplacer)")
    p.add_argument("file", type=Path)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--convention", type=Path, required=True)
    p.add_argument("--model")
    p.add_argument("--json", action="store_true", help="sortie JSON")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("propose-dir", help="propositions pour tous les fichiers d'un dossier (sans déplacement)")
    p.add_argument("folder", type=Path)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--convention", type=Path, required=True)
    p.add_argument("--model")
    p.set_defaults(func=cmd_propose_dir)

    p = sub.add_parser("eval", help="évaluer la qualité des propositions sur un jeu de test")
    p.add_argument("testset", type=Path)
    p.add_argument("--model")
    p.add_argument("-v", "--verbose", action="store_true", help="détailler les erreurs")
    p.add_argument("--min-score", type=float, help="échouer si moins de N %% de dossiers corrects (ex. 70)")
    p.set_defaults(func=cmd_eval)
