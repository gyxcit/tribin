"""Diagnostic de l'installation (« TriBin.exe --diagnostic ») : chargement des fournisseurs d'IA et du trousseau.

Écrit un rapport lisible dans le dossier des données (diagnostic.txt), sans jamais afficher de clé.
"""

from __future__ import annotations

import importlib
import platform
import sys
import traceback
from pathlib import Path

MODULES = ("tribin.llm.mistral_provider", "tribin.llm.gemini_provider", "tribin.llm.anthropic_provider", "keyring")


def report() -> str:
    lines = [f"TriBin — diagnostic ({'application empaquetée' if getattr(sys, 'frozen', False) else 'sources'})",
             f"Python {platform.python_version()} · {platform.platform()}", ""]
    for name in MODULES:
        try:
            importlib.import_module(name)
            lines.append(f"OK      {name}")
        except Exception:
            lines.append(f"ÉCHEC   {name}\n{traceback.format_exc()}")
    try:
        import keyring

        lines.append(f"Trousseau : {type(keyring.get_keyring()).__name__}")
    except Exception as exc:
        lines.append(f"Trousseau indisponible : {exc}")
    from tribin.config import PROVIDERS, read_api_key

    for provider in PROVIDERS:
        lines.append(f"Clé {provider} : {'présente' if read_api_key(provider) else 'absente'}")
    return "\n".join(lines) + "\n"


def write_report(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "diagnostic.txt"
    path.write_text(report(), encoding="utf-8")
    return path
