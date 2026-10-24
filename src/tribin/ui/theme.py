"""Thème de l'application (maquette Claude Design « TriBin — interface v2 », couleurs du logo).

Bleu nuit : boutons principaux et sélection. Turquoise / ambre / corail : niveaux de confiance
(sûr / à regarder / à vérifier), dans le même ordre que les trois barres du logo.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from tribin import resources

NAVY = "#1F2544"
NAVY_2 = "#2C3460"
INDIGO = "#3B4CCA"
INK = "#1F2544"
MUTED = "#5B6080"
FAINT = "#8A8FAE"
BACKGROUND = "#F6F7FB"
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

CHEVRON = Path(resources.__file__).with_name("chevron-down.svg").as_posix()
CHECK = Path(resources.__file__).with_name("check.svg").as_posix()

MONO_FAMILIES = ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "JetBrains Mono", "monospace"]

STYLESHEET = f"""
QMainWindow, QDialog, QWizard, QWizardPage {{ background: {SURFACE}; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 6px 8px; border-radius: 4px; }}

QFrame#Sidebar {{ background: {BACKGROUND}; border: none; border-right: 1px solid {BORDER}; }}
QFrame#Sidebar QLabel {{ background: transparent; }}
QLabel#Brand {{ font-size: 15px; font-weight: 600; }}
QPushButton#NavItem {{ background: transparent; border: none; border-radius: 6px; padding: 7px 10px; text-align: left;
    color: #3A4063; font-weight: 500; }}
QPushButton#NavItem:hover {{ background: #ECEEF6; }}
QPushButton#NavItem:checked {{ background: {SELECTION}; color: {INK}; font-weight: 600; }}
QLabel#NavCount {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
QLabel#AiStatus {{ color: {MUTED}; font-size: 12px; padding: 6px 10px; }}
QFrame#Divider {{ background: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}

QLabel#StepNum {{ border: 2px solid #D5D9E6; border-radius: 12px; background: white; color: {MUTED};
    font-size: 11px; font-weight: 600; }}
QLabel#StepNum[state="current"] {{ border-color: {NAVY}; color: {NAVY}; }}
QLabel#StepNum[state="done"] {{ border-color: {TEAL}; background: {TEAL}; color: white; }}
QLabel#StepText {{ color: {MUTED}; font-weight: 500; }}
QLabel#StepText[state="current"] {{ color: {INK}; font-weight: 600; }}
QLabel#RailNote {{ color: {FAINT}; font-size: 12px; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#SuggestCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#SuggestCard QLabel {{ background: transparent; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Faint {{ color: {FAINT}; font-size: 12px; }}
QLabel#Section {{ color: {INK}; font-size: 13px; font-weight: 600; }}
QLabel#FieldLabel {{ color: {MUTED}; }}
QLabel#Title {{ font-size: 20px; font-weight: 600; }}
QLabel#Big {{ font-size: 16px; font-weight: 600; }}
QLabel#Warning {{ background: #FDF0D5; color: #7A4606; border-radius: 8px; padding: 8px 10px; }}
QLabel#Empty {{ color: {MUTED}; font-size: 14px; }}
QLabel#Strike {{ color: {FAINT}; }}
QLabel#FileBadge {{ border-radius: 6px; color: white; font-size: 10px; font-weight: 700; }}

QPushButton {{ background: {SURFACE}; border: 1px solid #D5D9E6; border-radius: 8px; padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {NAVY}; }}
QPushButton:disabled {{ color: #A8ACC2; border-color: {BORDER}; }}
QPushButton#Primary {{ background: {NAVY}; color: white; border: 1px solid {NAVY}; }}
QPushButton#Primary:hover {{ background: {NAVY_2}; }}
QPushButton#Primary:disabled {{ background: #A8ACC2; border-color: #A8ACC2; color: white; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; color: #3A4063; font-weight: 500; }}
QPushButton#Ghost:hover {{ background: #F0F2FA; }}
QPushButton#Link {{ background: transparent; border: none; color: {INDIGO}; padding: 4px 2px; font-weight: 600; }}
QPushButton#Link:hover {{ color: {NAVY}; }}
QPushButton#Link:disabled {{ color: #A8ACC2; }}
QPushButton#Small {{ padding: 4px 10px; }}
QPushButton#Chip {{ border-radius: 14px; padding: 6px 12px; background: {SURFACE}; border: 1px solid #D5D9E6; font-weight: 500; }}
QPushButton#Chip:checked {{ background: {NAVY}; color: white; border-color: {NAVY}; font-weight: 600; }}
QPushButton#Chip:disabled {{ color: #A8ACC2; }}
QPushButton#Tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    padding: 8px 10px; color: {MUTED}; font-weight: 500; }}
QPushButton#Tab:checked {{ color: {INK}; border-bottom-color: {NAVY}; font-weight: 600; }}
QFrame#ChoiceCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#ChoiceCard[checked="true"] {{ border: 2px solid {NAVY}; background: #F6F7FC; }}
QFrame#ChoiceCard QLabel, QFrame#ChoiceCard QRadioButton {{ background: transparent; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 2px solid #B8BDD0; background: white; }}
QRadioButton::indicator:checked {{ border: 5px solid {NAVY}; width: 10px; height: 10px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 2px solid #B8BDD0; background: white; }}
QCheckBox::indicator:checked {{ border-color: {NAVY}; background: {NAVY}; image: url({CHECK}); }}
QLabel#Kbd {{ color: {MUTED}; background: #ECEEF4; border-radius: 4px; padding: 0 5px; font-size: 11px; font-weight: 600; }}
QLabel#KbdDark {{ color: white; background: #3A4170; border-radius: 4px; padding: 0 5px; font-size: 11px; font-weight: 600; }}
QLabel#BtnText {{ background: transparent; font-weight: 600; }}
QPushButton#Primary QLabel#BtnText {{ color: white; }}
QPushButton#Ghost QLabel#BtnText {{ font-weight: 500; color: #3A4063; }}

QLabel#Crumb {{ color: #3A4063; }}
QLabel#CrumbActive {{ color: {INK}; font-weight: 600; }}
QLabel#CrumbSep {{ color: #A0A5BC; }}

QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{
    background: {SURFACE}; border: 1px solid #D5D9E6; border-radius: 8px; padding: 7px 10px;
}}
QLineEdit, QPlainTextEdit {{ selection-background-color: {NAVY}; selection-color: white; }}
QComboBox, QDateEdit {{ selection-background-color: {SELECTION}; selection-color: {INK}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {NAVY}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: #A8ACC2; background: #FAFBFD; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({CHEVRON}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid #D5D9E6; outline: none; padding: 4px;
    selection-background-color: {SELECTION}; selection-color: {INK}; }}
QAbstractItemView::item:selected, QAbstractItemView::item:hover {{ background: {SELECTION}; color: {INK}; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; }}

QLabel#GroupTitle {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QListWidget#Queue {{ background: {SURFACE}; border: none; outline: none; }}
QListWidget#Queue::item {{ border: none; margin: 0; background: transparent; }}
QListWidget#Queue::item:selected {{ background: transparent; }}
QFrame#QueueRow {{ background: transparent; border: none; border-left: 3px solid transparent; }}
QFrame#QueueRow:hover {{ background: #F7F8FC; }}
QFrame#QueueRow[selected="true"] {{ background: #F0F2FA; border-left-color: {NAVY}; }}
QFrame#QueueRow QLabel {{ background: transparent; }}
QFrame#PaneFoot {{ background: {SURFACE}; border: none; border-top: 1px solid {BORDER}; }}
QFrame#PaneHead {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame#Pane {{ background: {SURFACE}; border: none; border-right: 1px solid {BORDER}; }}

QFrame#FolderRow {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#FolderRow QLabel {{ background: transparent; }}
QFrame#KeyStatus {{ background: #EEFAF7; border: 1px solid #BFEAE2; border-radius: 8px; }}
QFrame#KeyStatus QLabel {{ background: transparent; }}
QFrame#KeyStatus QLabel#KeyCheck {{ background: {TEAL}; color: white; border-radius: 11px; font-weight: 700; }}
QLabel#EmptyBox {{ border: 1px dashed #D5D9E6; border-radius: 8px; padding: 10px 12px; color: {FAINT}; }}

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
    return f"background: {background}; color: {text}; border-radius: 10px; padding: 2px 8px; font-weight: 600;"


def mono_font(point_size: float | None = None) -> QFont:
    """Police à chasse fixe pour les noms de fichiers (plus lisible pour 2026-10-12_ACME_…)."""
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    if point_size:
        font.setPointSizeF(point_size)
    return font


def apply_theme(app: QApplication) -> None:
    """Applique le thème clair à toute l'application (indépendant du thème du système)."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, BACKGROUND), (QPalette.ColorRole.Base, SURFACE),
                        (QPalette.ColorRole.AlternateBase, BACKGROUND), (QPalette.ColorRole.Text, INK),
                        (QPalette.ColorRole.WindowText, INK), (QPalette.ColorRole.Button, SURFACE),
                        (QPalette.ColorRole.ButtonText, INK), (QPalette.ColorRole.Highlight, SELECTION),
                        (QPalette.ColorRole.HighlightedText, INK), (QPalette.ColorRole.PlaceholderText, MUTED)]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    font = QFont("Segoe UI" if sys.platform == "win32" else ".AppleSystemUIFont" if sys.platform == "darwin" else "")
    font.setPointSizeF(10 if sys.platform == "win32" else 13)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
