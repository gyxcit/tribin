"""Ligne de commande : python -m tribin <commande>."""

from __future__ import annotations

import argparse
import sys

from tribin import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tribin", description="TriBin : rangement de fichiers assisté par IA.")
    parser.add_argument("--version", action="version", version=f"TriBin {__version__}")
    parser.add_subparsers(dest="command", metavar="<commande>")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
