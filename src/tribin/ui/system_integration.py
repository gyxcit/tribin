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


# --- afficher un fichier dans l'Explorateur / le Finder -------------------------------------------

FILE_MANAGER = "le Finder" if sys.platform == "darwin" else "l'Explorateur"


def reveal_target(*candidates: str | Path | None) -> Path | None:
    """Premier chemin existant parmi `candidates` ; à défaut, le premier dossier parent qui existe."""
    paths = [Path(c) for c in candidates if c]
    for path in paths:
        if path.exists():
            return path
    for path in paths:
        if path.parent.exists():
            return path.parent
    return None


def reveal(path: Path) -> None:
    """Ouvre l'Explorateur (Windows) ou le Finder (macOS) avec le fichier sélectionné ; un dossier est ouvert."""
    path = Path(path)
    if path.is_file() and sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{path}"')  # chaîne : explorer exige « /select,"chemin" » tel quel
    elif path.is_file() and sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))
