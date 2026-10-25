"""Raccourci clavier global (Windows) : Ctrl + Alt + T envoie à TriBin les fichiers sélectionnés dans l'Explorateur.

Le raccourci est enregistré auprès de Windows (RegisterHotKey) sur une fenêtre invisible ; il fonctionne même quand
TriBin est en arrière-plan. La sélection est lue dans la fenêtre de l'Explorateur au premier plan (Shell.Application).
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
HOTKEY_LABEL = "Ctrl + Alt + T"
DEFAULT_HOTKEY = (MOD_CONTROL | MOD_ALT, ord("T"))
GROUP_SEPARATOR = "----"

# Sélection de chaque onglet de la fenêtre de l'Explorateur `$h` (un groupe de chemins par onglet).
SELECTION_SCRIPT = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
    "$h = {hwnd};"
    "foreach ($w in (New-Object -ComObject Shell.Application).Windows()) {{"
    "  try {{ if ($w.HWND -eq $h) {{"
    "    $items = @($w.Document.SelectedItems() | ForEach-Object {{ $_.Path }});"
    "    if ($items.Count) {{ $items; '" + GROUP_SEPARATOR + "' }}"
    "  }} }} catch {{}}"
    "}}"
)


def parse_selection(output: str) -> list[list[Path]]:
    """Sortie du script -> une liste de chemins par onglet ayant une sélection."""
    groups, current = [], []
    for line in output.splitlines():
        line = line.strip()
        if line == GROUP_SEPARATOR:
            if current:
                groups.append(current)
            current = []
        elif line:
            current.append(Path(line))
    if current:
        groups.append(current)
    return groups


def foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow()) if sys.platform == "win32" else 0


def explorer_selection(hwnd: int) -> tuple[list[Path], str]:
    """Fichiers sélectionnés dans la fenêtre de l'Explorateur `hwnd` ; (chemins, message si rien n'est pris)."""
    if sys.platform != "win32" or not hwnd:
        return [], "Le raccourci fonctionne dans l'Explorateur Windows."
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             SELECTION_SCRIPT.format(hwnd=hwnd)], capture_output=True, timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    groups = parse_selection(result.stdout.decode("utf-8", errors="replace"))
    if not groups:
        return [], "Sélectionnez d'abord des fichiers dans l'Explorateur, puis appuyez sur " + HOTKEY_LABEL + "."
    if len(groups) > 1:  # plusieurs onglets avec une sélection : impossible de savoir lequel est affiché
        return [], ("Plusieurs onglets de l'Explorateur ont une sélection : gardez-en un seul, "
                    "ou glissez les fichiers sur le widget.")
    files = [p for p in groups[0] if p.is_file()]
    if not files:
        return [], "TriBin range des fichiers, pas des dossiers : sélectionnez des fichiers."
    return files, ""


class GlobalHotkey(QWidget):
    """Fenêtre invisible qui reçoit le raccourci global de Windows."""

    triggered = Signal()
    HOTKEY_ID = 0x7B1

    def __init__(self) -> None:
        super().__init__()
        self.registered = False

    def register(self, modifiers: int = DEFAULT_HOTKEY[0], key: int = DEFAULT_HOTKEY[1]) -> bool:
        if sys.platform != "win32":
            return False
        self.unregister()
        hwnd = int(self.winId())  # crée la fenêtre native (jamais affichée)
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(wintypes.HWND(hwnd), self.HOTKEY_ID,
                                                                   modifiers | MOD_NOREPEAT, key))
        if not self.registered:
            log.warning("raccourci global indisponible (déjà utilisé par une autre application ?)")
        return self.registered

    def unregister(self) -> None:
        if self.registered and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(wintypes.HWND(int(self.winId())), self.HOTKEY_ID)
        self.registered = False

    def nativeEvent(self, event_type, message):  # noqa: N802 — API Qt
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                self.triggered.emit()
                return True, 0
        return super().nativeEvent(event_type, message)
