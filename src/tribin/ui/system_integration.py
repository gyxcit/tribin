"""Intégration système : « Trier avec TriBin » au clic droit, « Envoyer vers > TriBin », raccourci sur le bureau
(Windows), et affichage d'un fichier dans l'Explorateur ou le Finder."""

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


# --- « Trier avec TriBin » au clic droit (compte de l'utilisateur seulement, HKCU) ---------------------

CONTEXT_MENU_KEY = r"Software\Classes\*\shell\TriBin"
CONTEXT_MENU_LABEL = "Trier avec TriBin"


def context_menu_command() -> str:
    program, args = app_command()
    return f'"{program}" {args} "%1"'.replace("  ", " ")


def install_context_menu(key_path: str = CONTEXT_MENU_KEY) -> str:
    """Ajoute « Trier avec TriBin » au clic droit des fichiers (Windows 11 : directement avec Maj + clic droit,
    sinon dans « Afficher d'autres options »). Réversible avec `uninstall_context_menu`."""
    if sys.platform != "win32":
        raise OSError("Le menu du clic droit de l'Explorateur n'existe que sous Windows.")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, CONTEXT_MENU_LABEL)
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, app_command()[0])
        winreg.SetValueEx(key, "Position", 0, winreg.REG_SZ, "Top")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, context_menu_command())
    return f"clic droit › {CONTEXT_MENU_LABEL}"


def uninstall_context_menu(key_path: str = CONTEXT_MENU_KEY) -> None:
    if sys.platform != "win32":
        return
    import winreg

    for path in (key_path + r"\command", key_path):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def context_menu_installed(key_path: str = CONTEXT_MENU_KEY) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            return bool(winreg.QueryValueEx(key, "")[0])
    except OSError:
        return False


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
