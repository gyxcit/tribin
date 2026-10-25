"""Outils partagés par les commandes : console, chargement de la convention, affichage des propositions."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from tribin.convention.loader import Convention, ConventionError, load_convention
from tribin.models import Proposal

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(highlight=False)


class CliError(Exception):
    """Erreur affichée proprement à l'utilisateur, sans trace technique."""


def load_convention_or_fail(path: Path) -> Convention:
    try:
        return load_convention(path)
    except ConventionError as exc:
        raise CliError(str(exc)) from exc


def confidence_label(p: Proposal) -> str:
    if p.manual:
        return "[red]à traiter manuellement[/red]"
    color = "green" if p.confidence >= 0.8 else "yellow" if p.confidence >= 0.6 else "red"
    label = f"[{color}]{p.confidence:.0%}[/{color}]"
    return label + (" [red]à vérifier[/red]" if p.needs_review else "")


def print_proposal(original_name: str, p: Proposal) -> None:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("[bold]Fichier[/bold]", original_name)
    table.add_row("[bold]Dossier[/bold]", (p.target_folder or "—") + (" [yellow](nouveau)[/yellow]" if p.folder_is_new else ""))
    table.add_row("[bold]Nom[/bold]", p.new_name)
    table.add_row("[bold]Confiance[/bold]", confidence_label(p))
    table.add_row("[bold]Explication[/bold]", p.reasoning or "—")
    if p.evidence:
        table.add_row("[bold]Indices[/bold]", " · ".join(p.evidence))
    if p.tool_calls:
        from tribin.engine.tools import looked_at

        table.add_row("[bold]Outils[/bold]", f"{len(p.tool_calls)} appel(s) ; a regardé : {', '.join(looked_at(p.tool_calls)) or '—'}")
    for w in p.warnings:
        table.add_row("[yellow]Attention[/yellow]", w)
    for i, alt in enumerate(p.alternatives, start=1):
        table.add_row(f"[dim]Alternative {i}[/dim]", f"{alt.target_folder}/{alt.new_name}\n[dim]{alt.reasoning}[/dim]")
    console.print(table)


def proposals_table(items: list[tuple[str, Proposal]]) -> Table:
    table = Table(title="Propositions", show_lines=False)
    table.add_column("Fichier d'origine")
    table.add_column("Dossier proposé")
    table.add_column("Nouveau nom")
    table.add_column("Confiance", justify="right")
    for name, p in items:
        table.add_row(name, p.target_folder or "—", p.new_name, confidence_label(p))
    return table
