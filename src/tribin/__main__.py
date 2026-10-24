"""Ligne de commande : python -m tribin <commande>."""

from __future__ import annotations

import argparse
import logging
import sys

from tribin import __version__

log = logging.getLogger("tribin")


def build_parser() -> argparse.ArgumentParser:
    from tribin.cli import map_cmd, propose_cmd

    parser = argparse.ArgumentParser(prog="tribin", description="TriBin : rangement de fichiers assisté par IA.")
    parser.add_argument("--version", action="version", version=f"TriBin {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<commande>")
    propose_cmd.register(sub)
    map_cmd.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    from tribin.cli.common import CliError, console
    from tribin.config import setup_logging

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    setup_logging()
    try:
        return args.func(args)
    except CliError as exc:
        console.print(f"[red]Erreur :[/red] {exc}")
        return 1
    except KeyboardInterrupt:
        console.print("Interrompu.")
        return 130
    except Exception as exc:  # jamais de trace brute pour l'utilisateur
        log.exception("unexpected error")
        console.print(f"[red]Erreur inattendue :[/red] {exc} (détails dans le journal technique tribin.log)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
