"""Commandes file, history, undo et create-structure (phase 3 : exécution sécurisée)."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.table import Table

from tribin.cli.common import CliError, console, load_convention_or_fail, print_proposal
from tribin.cli.propose_cmd import _context
from tribin.config import get_settings
from tribin.convention.naming import is_valid_name
from tribin.engine.proposer import normalize_rel, propose
from tribin.extract import extract
from tribin.fs.filters import ExclusionMatcher, NotProcessable, check_processable
from tribin.models import Proposal
from tribin.safety.executor import Executor, SimulationReport
from tribin.safety.journal import Journal
from tribin.safety.operations import Choice


def ask(question: str) -> str:
    try:
        return input(question).strip()
    except EOFError:
        return ""


def confirm(question: str, assume_yes: bool) -> bool:
    return assume_yes or ask(f"{question} [o/N] ").lower() in {"o", "oui", "y", "yes"}


def show_simulation(report: SimulationReport) -> None:
    console.print("[bold]Simulation[/bold] (aucun fichier n'a encore été touché) :")
    for line in report.lines():
        style = "red" if line.startswith(("✗", "    !")) else "dim" if line.startswith("    ·") else ""
        console.print(f"[{style}]{line}[/{style}]" if style else line, markup=bool(style))


def decision_meta(p: Proposal, folder: str, name: str, decision: str) -> dict:
    return {
        "file_id": p.file_id, "decision": decision, "prompt_version": p.prompt_version, "model": p.model,
        "ai_proposal": {"target_folder": p.target_folder, "new_name": p.new_name, "confidence": p.confidence},
        "final_choice": {"target_folder": folder, "new_name": name},
    }


def choose(p: Proposal, assume_yes: bool) -> tuple[str, str, str] | None:
    """Dialogue de validation : renvoie (dossier, nom, décision) ou None si l'utilisateur renonce."""
    folder, name, decision = p.target_folder, p.new_name, "accepted"
    if assume_yes:
        return (folder, name, decision) if folder else None
    while True:
        answer = ask("[Entrée] valider · (n) modifier le nom · (d) modifier le dossier · (1/2) alternative · (q) annuler : ").lower()
        if answer == "":
            return (folder, name, decision) if folder else None
        if answer == "q":
            return None
        if answer == "n":
            new = ask(f"Nouveau nom [{name}] : ") or name
            if not is_valid_name(new):
                console.print("[red]Nom invalide sous Windows ou macOS.[/red]")
                continue
            name, decision = new, "edited" if new != p.new_name or decision == "edited" else decision
        elif answer == "d":
            new = normalize_rel(ask(f"Nouveau dossier (relatif à la racine) [{folder}] : ") or folder)
            if new is None:
                console.print("[red]Le dossier doit rester dans la racine.[/red]")
                continue
            folder, decision = new, "edited" if new != p.target_folder or decision == "edited" else decision
        elif answer in {"1", "2"} and int(answer) <= len(p.alternatives):
            alt = p.alternatives[int(answer) - 1]
            folder, name, decision = alt.target_folder, alt.new_name, "alternative_chosen"
        console.print(f"→ {folder}/{name}")


def cmd_file(args: argparse.Namespace) -> int:
    ctx = _context(args.root, args.convention, args.model)
    try:
        check_processable(args.file, ctx.root, ExclusionMatcher(ctx.convention.excluded_paths))
    except NotProcessable as exc:
        raise CliError(str(exc)) from exc
    with console.status("Analyse du fichier…"):
        proposal = propose(extract(args.file), ctx)
    print_proposal(args.file.name, proposal)
    if proposal.manual and args.yes:
        raise CliError("Proposition à traiter manuellement : relance sans --yes pour choisir le dossier.")
    chosen = choose(proposal, args.yes)
    if not chosen:
        console.print("Rien n'a été déplacé.")
        return 0
    folder, name, decision = chosen
    executor = Executor([ctx.root], excluded=ctx.convention.excluded_paths)
    batch = executor.batch()
    batch.move(Choice(args.file, ctx.root, folder, name, decision_meta(proposal, folder, name, decision)))
    report = executor.simulate(batch.ops)
    show_simulation(report)
    if not report.ok:
        raise CliError("La simulation a détecté un problème : rien n'a été déplacé.")
    if not confirm("Exécuter ?", args.yes):
        console.print("Rien n'a été déplacé.")
        return 0
    result = executor.execute(batch.ops)
    _print_result(result.operations, batch.id)
    move = next((op for op in result.operations if op.action == "move" and op.status == "done"), None)
    if move is not None:
        _learn(ctx, args.file.name, proposal, folder, move, decision)
    return 0 if not result.failed else 1


def _learn(ctx, original_name: str, proposal: Proposal, folder: str, move, decision: str) -> None:
    """Apprentissage : la décision devient une correction ; l'emplacement est mémorisé (signal implicite)."""
    from tribin.db import Database
    from tribin.learning.corrections import record_correction
    from tribin.learning.signals import maybe_summarize, remember_placement

    db = Database(get_settings().db_path)
    record_correction(db, ctx.convention, original_name, proposal.excerpt, proposal.client_hint, proposal, folder,
                      move.destination.name, decision)
    remember_placement(db, move.operation_id, move.destination, ctx.root, folder, move.destination.name,
                       original_name, proposal.client_hint)
    if decision != "accepted":
        maybe_summarize(db, ctx.llm) if not result.failed else 1


def _print_result(operations, batch_id: str) -> None:
    for op in operations:
        mark = {"done": "[green]✓[/green]", "failed": "[red]✗[/red]", "skipped": "[yellow]–[/yellow]"}.get(op.status, "?")
        console.print(f"{mark} {op.describe()}" + (f" — {op.error}" if op.error else ""))
    console.print(f"Lot {batch_id} : annulable avec « tribin undo --batch {batch_id} ».")


def cmd_history(args: argparse.Namespace) -> int:
    journal = Journal(get_settings().journal_dir)
    ops = journal.operations(batch_id=args.batch)[: args.limit]
    table = Table(title="Historique des opérations")
    for col in ("Date", "Lot", "Opération", "Action", "Statut", "Source → destination"):
        table.add_column(col)
    for op in ops:
        table.add_row(op.get("ts", "")[:19].replace("T", " "), op.get("batch_id", ""), op["operation_id"],
                      op.get("action", ""), op.get("status", ""), f"{op.get('source') or ''} → {op.get('destination', '')}")
    console.print(table)
    rate = journal.acceptance_rate()
    if rate is not None:
        console.print(f"Propositions acceptées sans modification : {rate:.0%}")
    console.print(f"[dim]Journal : {journal.dir}[/dim]")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    if not (args.batch or args.operation):
        raise CliError("Précise --batch <id> ou --operation <id> (voir « tribin history »).")
    settings = get_settings()
    roots = [Path(op["root"]) for op in Journal(settings.journal_dir).states().values() if op.get("root")]
    executor = Executor(roots or [Path.cwd()])
    preview = executor.undo(args.operation, args.batch, execute=False)
    if not preview:
        raise CliError("Aucune opération annulable pour cette sélection.")
    for r in preview:
        console.print(f"{r['status']:10} {r['action']:8} {r['from']} → {r['to'] or '-'} {r['message']}")
    if not confirm("Annuler ces opérations ?", args.yes):
        return 0
    for r in executor.undo(args.operation, args.batch, execute=True):
        console.print(f"{r['status']:10} {r['action']:8} {r['from']} → {r['to'] or '-'} {r['message']}")
    return 0


def cmd_create_structure(args: argparse.Namespace) -> int:
    convention = load_convention_or_fail(args.convention)
    executor = Executor([args.root], excluded=convention.excluded_paths)
    batch = executor.batch()
    if args.client:
        client = convention.client_by_code(args.client)
        if not client:
            raise CliError(f"Client inconnu dans la convention : {args.client}")
        if not (args.year and args.project):
            raise CliError("Avec --client, précise aussi --year et --project (ex. 2026-050_Salon).")
        base = convention.structure.template.split("{category}")[0].format(
            client=client.code, year=args.year, project=args.project).rstrip("/")
        for category in convention.category_codes():
            batch.mkdirs(args.root, f"{base}/{category}")
    else:
        for client in convention.clients:
            batch.mkdirs(args.root, client.code)
    if not batch.ops:
        console.print("Tous les dossiers existent déjà.")
        return 0
    report = executor.simulate(batch.ops)
    show_simulation(report)
    if not report.ok:
        raise CliError("La simulation a détecté un problème : rien n'a été créé.")
    if not confirm(f"Créer ces {len(batch.ops)} dossier(s) ?", args.yes):
        return 0
    _print_result(executor.execute(batch.ops).operations, batch.id)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("file", help="proposer, simuler puis ranger un fichier")
    p.add_argument("file", type=Path)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--convention", type=Path, required=True)
    p.add_argument("--model")
    p.add_argument("--yes", action="store_true", help="valider sans poser de question")
    p.set_defaults(func=cmd_file)

    p = sub.add_parser("history", help="historique des opérations du journal")
    p.add_argument("--batch")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("undo", help="annuler une opération ou un lot")
    p.add_argument("--batch")
    p.add_argument("--operation")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("create-structure", help="créer les dossiers de la convention (simulation obligatoire)")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--convention", type=Path, required=True)
    p.add_argument("--client")
    p.add_argument("--year")
    p.add_argument("--project", help="nom du dossier projet, ex. 2026-050_Salon")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_create_structure)
