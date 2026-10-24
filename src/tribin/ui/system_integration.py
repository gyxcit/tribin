"""Intégration système : « Envoyer vers > TriBin » et raccourci sur le bureau (Windows)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def app_command() -> tuple[str, str]:
    """Programme et arguments qui lancent TriBin (exécutable empaqueté ou interpréteur Python)."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else sys.executable), "-m tribin.ui.app"


def _create_shortcut(link: Path, target: str, arguments: str) -> None:
    """Crée un raccourci .lnk via WScript.Shell (aucune dépendance supplémentaire)."""
    def ps(value: str) -> str:
        return value.replace("'", "''")

    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{ps(str(link))}');"
              f"$s.TargetPath='{ps(target)}';$s.Arguments='{ps(arguments)}';"
              f"$s.WorkingDirectory='{ps(str(Path(target).parent))}';$s.Description='TriBin';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def sendto_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo"


def install_sendto() -> Path:
    """Ajoute « Envoyer vers > TriBin » au clic droit de l'Explorateur Windows."""
    if sys.platform != "win32":
        raise OSError("« Envoyer vers » n'existe que sous Windows.")
    link = sendto_dir() / "TriBin.lnk"
    if link.exists():
        return link
    _create_shortcut(link, *app_command())
    return link


def install_desktop_shortcut() -> Path:
    """Raccourci sur le bureau : y glisser des fichiers les envoie à TriBin."""
    if sys.platform != "win32":
        raise OSError("Raccourci de bureau : fonction Windows (sous macOS, utilise l'icône du Dock).")
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    link = desktop / "TriBin.lnk"
    if link.exists():
        return link
    _create_shortcut(link, *app_command())
    return link
