"""Thème de l'application, construit à partir des couleurs du logo (maquette Claude Design « TriBin — nouvelle interface »).

Bleu nuit : structure (bandeau, boutons principaux). Turquoise / ambre / corail : niveaux de confiance
(sûr / à regarder / à vérifier), dans le même ordre que les trois barres du logo.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

NAVY = "#1F2544"
NAVY_2 = "#2C3460"
INDIGO = "#3B4CCA"
INK = "#1F2544"
MUTED = "#5B6080"
FAINT = "#8A8FAE"
BACKGROUND = "#F5F6FA"
SURFACE = "#FFFFFF"
BORDER = "#E2E5EF"
BORDER_STRONG = "#C9CDE6"
SELECTION = "#E8EAF6"
TEAL = "#14B8A6"
AMBER = "#F5A524"
CORAL = "#F0605A"

# Niveaux de confiance : (clé, libellé, fond de pastille, texte de pastille)
LEVEL_SURE = ("sure", "Sûr", "#DDF5F1", "#0F766E")
LEVEL_LOOK = ("look", "À regarder", "#FDF0D5", "#8A4B05")
LEVEL_CHECK = ("check", "À vérifier", "#FDE4E2", "#A42A25")
LEVEL_WAIT = ("wait", "Analyse…", "#ECEEF4", "#5B6080")

MONO_FAMILIES = ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "JetBrains Mono", "monospace"]

STYLESHEET = f"""
* {{ color: {INK}; }}
QMainWindow, QDialog, QWizard, QWizardPage {{ background: {BACKGROUND}; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 6px 8px; border-radius: 4px; }}

QFrame#Header {{ background: {NAVY}; }}
QFrame#Header QLabel {{ color: white; background: transparent; }}
QLabel#Brand {{ font-size: 18px; font-weight: 700; }}
QLabel#HeaderTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#HeaderSubtitle {{ color: #B9BEDA; }}
QPushButton#NavTab {{ background: transparent; color: #C9CDE6; border: none; border-radius: 8px; padding: 8px 14px; }}
QPushButton#NavTab:hover {{ color: white; }}
QPushButton#NavTab:checked {{ background: {NAVY_2}; color: white; font-weight: 600; }}
QFrame#Header QLabel#HeaderChip {{ background: {NAVY_2}; color: #E3E6F5; border-radius: 13px; padding: 5px 12px; }}
QFrame#Header QLabel#PendingChip {{ background: {AMBER}; color: {NAVY}; border-radius: 13px; padding: 5px 12px; font-weight: 700; }}
QFrame#Header QPushButton {{ background: transparent; color: white; border: 1px solid #4A5280; }}
QFrame#Header QPushButton:hover {{ background: {NAVY_2}; }}
QFrame#Header QPushButton#NavTab {{ border: none; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Section {{ color: {MUTED}; font-size: 11px; font-weight: 700; }}
QLabel#Title {{ font-size: 22px; font-weight: 700; }}
QLabel#Big {{ font-size: 16px; font-weight: 600; }}
QLabel#Warning {{ background: #FDF0D5; color: #7A4606; border-radius: 8px; padding: 8px 10px; }}
QLabel#Empty {{ color: {MUTED}; font-size: 14px; }}
QLabel#Strike {{ color: {MUTED}; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 8px 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {NAVY}; }}
QPushButton:disabled {{ color: #A8ACC2; border-color: {BORDER}; }}
QPushButton#Primary {{ background: {NAVY}; color: white; border: none; font-weight: 700; }}
QPushButton#Primary:hover {{ background: {NAVY_2}; }}
QPushButton#Primary:disabled {{ background: #A8ACC2; color: white; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {MUTED}; }}
QPushButton#Ghost:hover {{ color: {INK}; }}
QPushButton#Link {{ background: transparent; border: none; color: {INDIGO}; padding: 4px 6px; }}
QPushButton#Link:hover {{ color: {NAVY}; }}
QPushButton#Chip {{ border-radius: 14px; padding: 6px 12px; background: {SURFACE}; border: 1px solid {BORDER_STRONG}; font-weight: 500; }}
QPushButton#Chip:checked {{ background: {NAVY}; color: white; border-color: {NAVY}; font-weight: 600; }}
QPushButton#Chip:disabled {{ color: #A8ACC2; }}
QLabel#Kbd {{ color: {MUTED}; border: 1px solid {BORDER}; border-radius: 4px; padding: 0 5px; font-size: 11px; background: transparent; }}
QLabel#KbdDark {{ color: #C9CDE6; border: 1px solid #4A5280; border-radius: 4px; padding: 0 5px; font-size: 11px; background: transparent; }}
QLabel#BtnText {{ background: transparent; font-weight: 700; }}
QPushButton#Primary QLabel#BtnText {{ color: white; }}

QLabel#Crumb {{ background: {BACKGROUND}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 10px; }}
QLabel#CrumbActive {{ background: {NAVY}; color: white; border-radius: 8px; padding: 5px 10px; font-weight: 600; }}
QLabel#CrumbSep {{ color: {FAINT}; }}

QFrame#AltCard {{ background: #FDF6E7; border: 1px solid #F6DCA6; border-radius: 10px; }}
QFrame#AltCard QLabel {{ background: transparent; }}
QPushButton#AltButton {{ background: white; border: 1px solid #E0B866; color: #6B4200; }}

QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: {NAVY};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {NAVY}; }}
QLineEdit#Search {{ border-color: {BORDER}; border-radius: 10px; padding: 9px 12px; }}
QLineEdit#NewName {{ background: #FAFBFE; font-size: 14px; padding: 9px 12px; }}

QLabel#GroupReview {{ color: #A42A25; font-size: 11px; font-weight: 700; }}
QLabel#GroupReady {{ color: #0F766E; font-size: 11px; font-weight: 700; }}
QLabel#GroupWait {{ color: {MUTED}; font-size: 11px; font-weight: 700; }}
QListWidget#Queue {{ background: {BACKGROUND}; border: none; outline: none; }}
QListWidget#Queue::item {{ border: none; margin: 2px 0; background: transparent; }}
QListWidget#Queue::item:selected {{ background: transparent; }}
QFrame#QueueRow {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#QueueRow[selected="true"] {{ border: 2px solid {NAVY}; background: {SELECTION}; }}
QFrame#QueueRow QLabel {{ background: transparent; }}

QFrame#OpRow {{ border-radius: 10px; border: 1px solid #D4EFEA; background: #F7FAF9; }}
QFrame#OpRow[kind="archive"] {{ border-color: #F6DCA6; background: #FDF9EF; }}
QFrame#OpRow[kind="mkdir"] {{ border-color: {BORDER}; background: {BACKGROUND}; }}
QFrame#OpRow[kind="problem"] {{ border-color: #F4B9B5; background: #FDF1F0; }}
QFrame#OpRow QLabel {{ background: transparent; }}

QTableWidget, QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {BORDER}; selection-background-color: {SELECTION}; selection-color: {INK}; }}
QHeaderView::section {{ background: {BACKGROUND}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; font-weight: 600; color: {MUTED}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {SURFACE}; top: -1px; }}
QTabBar::tab {{ padding: 7px 14px; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {NAVY}; font-weight: 600; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #CDD1E0; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def level_for(confidence: float | None, manual: bool = False, waiting: bool = False) -> tuple[str, str, str, str]:
    """Niveau de confiance : (clé, libellé, fond, texte). Seuils : 0,8 et 0,6 (marqueur « à vérifier »)."""
    if waiting:
        return LEVEL_WAIT
    if manual or confidence is None or confidence < 0.6:
        return LEVEL_CHECK
    return LEVEL_SURE if confidence >= 0.8 else LEVEL_LOOK


def pill_colors(confidence: float | None, manual: bool = False, waiting: bool = False) -> tuple[str, str]:
    _, _, background, text = level_for(confidence, manual, waiting)
    return background, text


def pill_style(colors: tuple[str, str]) -> str:
    background, text = colors
    return f"background: {background}; color: {text}; border-radius: 11px; padding: 3px 10px; font-weight: 700;"


def mono_font(point_size: float | None = None) -> QFont:
    """Police à chasse fixe pour les noms de fichiers (plus lisible pour 2026-10-12_ACME_…)."""
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    if point_size:
        font.setPointSizeF(point_size)
    return font


def header_bar(title: str, subtitle: str = ""):
    """Bandeau bleu nuit avec le logo (boîtes de dialogue)."""
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

    from tribin.ui.icons import logo_pixmap

    header = QFrame()
    header.setObjectName("Header")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(18, 12, 18, 12)
    logo = QLabel()
    logo.setPixmap(logo_pixmap(34))
    layout.addWidget(logo)
    titles = QVBoxLayout()
    titles.setSpacing(0)
    title_label = QLabel(title)
    title_label.setObjectName("HeaderTitle")
    titles.addWidget(title_label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("HeaderSubtitle")
        titles.addWidget(sub)
    layout.addLayout(titles)
    layout.addStretch()
    return header


def apply_theme(app: QApplication) -> None:
    """Applique le thème clair à toute l'application (indépendant du thème du système)."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, BACKGROUND), (QPalette.ColorRole.Base, SURFACE),
                        (QPalette.ColorRole.AlternateBase, BACKGROUND), (QPalette.ColorRole.Text, INK),
                        (QPalette.ColorRole.WindowText, INK), (QPalette.ColorRole.Button, SURFACE),
                        (QPalette.ColorRole.ButtonText, INK), (QPalette.ColorRole.Highlight, NAVY),
                        (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.PlaceholderText, MUTED)]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    font = QFont("Segoe UI" if sys.platform == "win32" else ".AppleSystemUIFont" if sys.platform == "darwin" else "")
    font.setPointSizeF(10 if sys.platform == "win32" else 13)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
