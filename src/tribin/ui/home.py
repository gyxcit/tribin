"""Accueil : bannière, statistiques (rangés, sans correction, corrigés par vous, automatiques) et 5 derniers rangements."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QSize, Qt, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tribin.safety.journal import Journal
from tribin.service.activity import Placement, compute_stats, placements
from tribin.ui.components import FileBadge, elided, muted
from tribin.ui.icons import line_icon, logo_pixmap
from tribin.ui.system_integration import FILE_MANAGER, reveal, reveal_target

if TYPE_CHECKING:
    from tribin.ui.app import AppController

RECENT_COUNT = 5
STYLE = """
QFrame#Banner { border-radius: 14px; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1F2544, stop:0.65 #2C3460, stop:1 #3B4CCA); }
QFrame#Banner QLabel { color: white; background: transparent; }
QLabel#BannerTitle { font-size: 22px; font-weight: 600; }
QLabel#BannerSub { color: #C9CDE6; }
QPushButton#BannerButton { background: white; color: #1F2544; border: none; border-radius: 8px; padding: 9px 16px;
    font-weight: 600; }
QPushButton#BannerButton:hover { background: #E8EAF6; }
QFrame#StatCard { background: white; border: 1px solid #E2E5EF; border-radius: 12px; }
QFrame#StatCard QLabel { background: transparent; }
QLabel#StatValue { font-size: 26px; font-weight: 700; color: #1F2544; }
QLabel#StatLabel { font-weight: 600; color: #3A4063; }
QFrame#RecentCard { background: white; border: 1px solid #E2E5EF; border-radius: 12px; }
QFrame#RecentCard QLabel { background: transparent; }
QFrame#RecentRow { border: none; border-top: 1px solid #EEF0F6; background: transparent; }
"""


def ago(when: datetime, now: datetime | None = None) -> str:
    """« à l'instant », « il y a 5 min », « il y a 2 h », « hier à 14:02 », « 12/10 à 09:30 »."""
    now = now or datetime.now()
    seconds = (now - when).total_seconds()
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {int(seconds // 60)} min"
    if when.date() == now.date():
        return f"il y a {int(seconds // 3600)} h"
    if (now.date() - when.date()).days == 1:
        return f"hier à {when:%H:%M}"
    return f"{when:%d/%m} à {when:%H:%M}"


def open_file(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def icon_button(icon: str, tooltip: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName("Ghost")
    button.setIcon(line_icon(icon, "#3A4063", 16))
    button.setIconSize(QSize(16, 16))
    button.setToolTip(tooltip)
    button.setFixedSize(32, 30)
    return button


class StatCard(QFrame):
    """Chiffre clé, animé à l'affichage (de 0 à la valeur)."""

    def __init__(self, icon: str, label: str, color: str):
        super().__init__()
        self.setObjectName("StatCard")
        self.suffix = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)
        head = QHBoxLayout()
        glyph = QLabel()
        glyph.setPixmap(line_icon(icon, color, 18).pixmap(18, 18))
        title = QLabel(label)
        title.setObjectName("StatLabel")
        head.addWidget(glyph)
        head.addWidget(title, 1)
        layout.addLayout(head)
        layout.addSpacing(6)
        self.value = QLabel("0")
        self.value.setObjectName("StatValue")
        layout.addWidget(self.value)
        self.caption = muted()
        layout.addWidget(self.caption)
        self.target = 0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(700)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(lambda v: self.value.setText(f"{int(v)}{self.suffix}"))

    def set_value(self, value: int | None, caption: str, suffix: str = "") -> None:
        self.caption.setText(caption)
        self.suffix = suffix
        if value is None:
            self.animation.stop()
            self.value.setText("—")
            return
        self.target = value
        self.animation.stop()
        self.animation.setStartValue(0)
        self.animation.setEndValue(value)
        self.animation.start()
        self.value.setText(f"{value}{suffix}")  # valeur finale tout de suite si l'animation ne tourne pas


class HomeView(QWidget):
    open_queue = Signal()
    open_history = Signal()

    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        wrapper = QHBoxLayout(page)
        wrapper.setContentsMargins(28, 24, 28, 24)
        box = QWidget()
        box.setMaximumWidth(1080)
        wrapper.addStretch()
        wrapper.addWidget(box, 100)
        wrapper.addStretch()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(18)

        # --- bannière ---
        banner = QFrame()
        banner.setObjectName("Banner")
        row = QHBoxLayout(banner)
        row.setContentsMargins(26, 22, 26, 22)
        row.setSpacing(18)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(52))
        row.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.greeting = QLabel()
        self.greeting.setObjectName("BannerTitle")
        self.banner_sub = QLabel()
        self.banner_sub.setObjectName("BannerSub")
        self.banner_sub.setWordWrap(True)
        texts.addWidget(self.greeting)
        texts.addWidget(self.banner_sub)
        row.addLayout(texts, 1)
        self.queue_button = QPushButton()
        self.queue_button.setObjectName("BannerButton")
        self.queue_button.clicked.connect(self.open_queue)
        row.addWidget(self.queue_button, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(banner)

        # --- statistiques ---
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.cards = {
            "filed": StatCard("files", "Fichiers rangés", "#1F2544"),
            "rate": StatCard("check", "Sans correction", "#0F766E"),
            "corrected": StatCard("edit", "Corrigés par vous", "#8A4B05"),
            "auto": StatCard("bolt", "Rangés automatiquement", "#3B4CCA"),
        }
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, 0, index)
            grid.setColumnStretch(index, 1)
        column.addLayout(grid)

        # --- derniers rangements ---
        recent = QFrame()
        recent.setObjectName("RecentCard")
        self.recent_layout = QVBoxLayout(recent)
        self.recent_layout.setContentsMargins(20, 16, 20, 8)
        self.recent_layout.setSpacing(0)
        head = QHBoxLayout()
        title = QLabel("Derniers rangements")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch()
        see_all = QPushButton("Voir tout l'historique")
        see_all.setObjectName("Link")
        see_all.setIcon(line_icon("arrow-right", "#3B4CCA", 14))
        see_all.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        see_all.clicked.connect(self.open_history)
        head.addWidget(see_all)
        self.recent_layout.addLayout(head)
        self.recent_layout.addSpacing(10)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(0)
        self.recent_layout.addLayout(self.rows)
        column.addWidget(recent)
        column.addStretch()

    # --- données ------------------------------------------------------------------------------

    def reload(self) -> None:
        items = placements(Journal(self.c.service.settings.journal_dir))
        stats = compute_stats(items)
        pending = self.c.service.pending()
        from tribin.service.account import get_account

        name = get_account(self.c.service.db, self.c.service.settings.user).display_name.split()[0]
        hello = "Bonsoir" if datetime.now().hour >= 18 else "Bonjour"
        self.greeting.setText(f"{hello}{', ' + name if name else ''} !")
        month = stats.this_month
        self.banner_sub.setText(
            (f"TriBin a rangé {month} fichier{'s' if month > 1 else ''} ce mois-ci." if month
             else "Glissez des fichiers sur le widget « Trier » : TriBin vous dit où les ranger.")
            + (f" {len(pending)} en attente." if pending else " Rien en attente."))
        self.queue_button.setText(f"Voir les {len(pending)} à ranger" if len(pending) > 1
                                  else "Voir le fichier à ranger" if pending else "Tout est rangé")
        self.queue_button.setEnabled(bool(pending))

        rate = stats.without_correction
        self.cards["filed"].set_value(stats.filed, f"dont {stats.this_month} ce mois-ci")
        self.cards["rate"].set_value(round(rate * 100) if rate is not None else None,
                                     "des propositions, sans retouche" if rate is not None else "pas encore de mesure",
                                     " %")
        self.cards["corrected"].set_value(stats.corrected, "retours humains, appris par TriBin")
        self.cards["auto"].set_value(stats.auto, "sans aucun clic de votre part")
        self._fill_recent([p for p in items if p.status == "done" and p.decision != "reorganisation"][:RECENT_COUNT])

    def _fill_recent(self, recent: list[Placement]) -> None:
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        if not recent:
            empty = muted("Aucun rangement pour l'instant : glissez un fichier sur le widget « Trier ».")
            empty.setContentsMargins(0, 8, 0, 14)
            self.rows.addWidget(empty)
            empty.show()
            return
        for placement in recent:
            row = self._recent_row(placement)
            self.rows.addWidget(row)
            row.show()

    def _recent_row(self, p: Placement) -> QFrame:
        row = QFrame()
        row.setObjectName("RecentRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 10, 0, 10)
        line.setSpacing(12)
        badge = FileBadge(34)
        badge.set_path(p.destination)
        line.addWidget(badge)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel()
        name.setStyleSheet("font-weight: 500;")
        name.setText(elided(p.name, name, 420))
        name.setToolTip(str(p.destination))
        where = muted(wrap=False)
        where.setText(elided(" › ".join(x for x in p.folder.split("/") if x), where, 420))
        texts.addWidget(name)
        texts.addWidget(where)
        line.addLayout(texts, 1)
        when = muted(ago(p.when), wrap=False)
        when.setToolTip(f"{p.when:%d/%m/%Y à %H:%M}")
        line.addWidget(when)
        target = reveal_target(p.current_path)
        exists = bool(p.current_path and p.current_path.is_file())
        open_button = icon_button("open", "Ouvrir le fichier")
        open_button.setEnabled(exists)
        open_button.clicked.connect(lambda _=False, path=p.current_path: open_file(path))
        show_button = icon_button("folder", f"Afficher dans {FILE_MANAGER}")
        show_button.setEnabled(target is not None)
        show_button.clicked.connect(lambda _=False, t=target: reveal(t))
        line.addWidget(open_button)
        line.addWidget(show_button)
        return row
