"""Thème de l'application, construit à partir des couleurs du logo.

Bleu nuit : structure (en-têtes, boutons principaux). Turquoise / ambre / corail : niveaux de confiance
(sûr / à regarder / à vérifier), dans le même ordre que les trois barres du logo.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

NAVY = "#1F2544"
NAVY_HOVER = "#2C3460"
INK = "#1F2544"
MUTED = "#6B7090"
BACKGROUND = "#F5F6FA"
SURFACE = "#FFFFFF"
BORDER = "#E2E5EF"
SELECTION = "#E8EAF6"
TEAL = "#14B8A6"
AMBER = "#F5A524"
CORAL = "#F0605A"

# (fond, texte) des pastilles de confiance
PILL_SURE = ("#DDF5F1", "#0F766E")
PILL_LOOK = ("#FDF0D5", "#A15C07")
PILL_CHECK = ("#FDE4E2", "#B4332D")
PILL_WAIT = ("#ECEEF4", "#6B7090")

STYLESHEET = f"""
* {{ color: {INK}; }}
QMainWindow, QDialog, QWizard, QWizardPage {{ background: {BACKGROUND}; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 6px 8px; border-radius: 4px; }}

QFrame#Header {{ background: {NAVY}; }}
QFrame#Header QLabel {{ color: white; }}
QLabel#HeaderTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#HeaderSubtitle {{ color: #B9BEDA; }}
QFrame#Header QPushButton {{ background: transparent; color: white; border: 1px solid #4A5280; }}
QFrame#Header QPushButton:hover {{ background: {NAVY_HOVER}; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Section {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Big {{ font-size: 16px; font-weight: 600; }}
QLabel#Warning {{ background: #FDF0D5; color: #7A4606; border-radius: 6px; padding: 6px 8px; }}
QLabel#Empty {{ color: {MUTED}; font-size: 15px; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {NAVY}; }}
QPushButton:disabled {{ color: #A8ACC2; }}
QPushButton#Primary {{ background: {NAVY}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {NAVY_HOVER}; }}
QPushButton#Primary:disabled {{ background: #A8ACC2; }}
QPushButton#Chip {{ border-radius: 12px; padding: 4px 12px; background: {SELECTION}; border: none; }}
QPushButton#Chip:hover {{ background: #D6DAF0; }}

QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {NAVY};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {NAVY}; }}

QListWidget#Queue {{ background: {BACKGROUND}; border: none; outline: none; }}
QListWidget#Queue::item {{ border: none; margin: 2px 0; }}
QListWidget#Queue::item:selected {{ background: transparent; }}
QFrame#QueueRow {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#QueueRow[selected="true"] {{ border: 2px solid {NAVY}; background: {SELECTION}; }}

QTableWidget, QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {BORDER}; selection-background-color: {SELECTION}; selection-color: {INK}; }}
QHeaderView::section {{ background: {BACKGROUND}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; font-weight: 600; color: {MUTED}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {SURFACE}; top: -1px; }}
QTabBar::tab {{ padding: 7px 14px; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {NAVY}; font-weight: 600; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #CDD1E0; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def pill_colors(confidence: float | None, manual: bool = False, waiting: bool = False) -> tuple[str, str]:
    """Couleurs de la pastille de confiance : turquoise (sûr), ambre (à regarder), corail (à vérifier)."""
    if waiting:
        return PILL_WAIT
    if manual or confidence is None or confidence < 0.6:
        return PILL_CHECK
    return PILL_SURE if confidence >= 0.8 else PILL_LOOK


def pill_style(colors: tuple[str, str]) -> str:
    background, text = colors
    return f"background: {background}; color: {text}; border-radius: 10px; padding: 2px 9px; font-weight: 600;"


def header_bar(title: str, subtitle: str = ""):
    """Bandeau bleu nuit avec le logo, commun aux fenêtres de l'application."""
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
