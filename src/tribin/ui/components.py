"""Composants visuels réutilisables : pastille de confiance, jauge, fil d'Ariane, bouton avec raccourci, aperçus."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from tribin.service.queue import QueueItem
from tribin.ui.theme import NAVY, level_for, pill_style

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
PREVIEW_EXT = {".pdf", ".ai", ".psd"}


# --- textes -----------------------------------------------------------------------------------


def section(text: str, name: str = "Section") -> QLabel:
    """Petit titre de section en capitales (« DESTINATION », « POURQUOI… »)."""
    label = QLabel(text.upper())
    label.setObjectName(name)
    return label


def elided(text: str, widget: QWidget, width: int, mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> str:
    return QFontMetrics(widget.font()).elidedText(text, mode, width)


def item_level(item: QueueItem) -> tuple[str, str, str, str]:
    """Niveau de confiance d'un fichier en attente (analyse en cours, erreur, manuel compris)."""
    p = item.proposal
    return level_for(p.confidence if p else None, manual=bool(p and p.manual) or item.status == "error",
                     waiting=item.status == "analyzing")


def short_confidence(item: QueueItem) -> str:
    """Pastille courte de la liste : « 92 % », « Analyse… », « À traiter »."""
    if item.status == "analyzing":
        return "Analyse…"
    if item.status == "error" or not item.proposal or item.proposal.manual:
        return "À traiter"
    return f"{item.proposal.confidence:.0%}".replace("%", " %")


class Pill(QLabel):
    """Pastille colorée (niveau de confiance ou statut)."""

    def __init__(self, text: str = "", colors: tuple[str, str] = ("#ECEEF4", "#5B6080")):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_colors(colors)

    def set_colors(self, colors: tuple[str, str]) -> None:
        self.setStyleSheet(pill_style(colors))


# --- bouton avec raccourci ----------------------------------------------------------------------


class KeyButton(QPushButton):
    """Bouton « Valider et ranger  [Entrée] » : libellé et touche de raccourci affichée."""

    def __init__(self, text: str, key: str = "", kind: str = ""):
        super().__init__()
        if kind:
            self.setObjectName(kind)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 14, 0)
        layout.setSpacing(8)
        self.label = QLabel(text)
        self.label.setObjectName("BtnText")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label)
        if key:
            hint = QLabel(key)
            hint.setObjectName("KbdDark" if kind == "Primary" else "Kbd")
            hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            hint.setFixedHeight(18)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(42)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:  # noqa: N802 — API Qt
        hint = self.layout().sizeHint()
        return QSize(hint.width() + 8, max(42, hint.height()))


# --- jauge de confiance ---------------------------------------------------------------------------


class ConfidenceGauge(QWidget):
    """Barre en trois zones (à vérifier < 60 % < à regarder < 80 % < sûr) et un repère."""

    ZONES = ((0.6, "#F9C9C6"), (0.2, "#FBE1B0"), (0.2, "#B7EAE2"))

    def __init__(self) -> None:
        super().__init__()
        self.value: float | None = None
        self.setFixedHeight(20)
        self.setAccessibleName("Confiance de l'IA")

    def set_value(self, value: float | None) -> None:
        self.value = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — API Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, top, height, gap = self.width(), 5, 10, 3
        x = 0.0
        for share, color in self.ZONES:
            w = width * share - gap
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, top, max(0.0, w), height), 4, 4)
            x += width * share
        if self.value is not None:
            marker = max(2.0, min(width - 2.0, width * self.value))
            p.setBrush(QColor(NAVY))
            p.drawRoundedRect(QRectF(marker - 2, 0, 4, 20), 2, 2)
        p.end()


# --- fil d'Ariane ---------------------------------------------------------------------------------


class Breadcrumb(QWidget):
    """Destination en étapes : Client › Année › Projet › Catégorie (la dernière en bleu nuit)."""

    def __init__(self) -> None:
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(6)

    def set_parts(self, parts: list[str]) -> None:
        while self.row.count():
            widget = self.row.takeAt(0).widget()
            if widget:
                widget.hide()  # sinon visible jusqu'à sa destruction effective
                widget.deleteLater()
        if not parts:
            empty = QLabel("Aucun dossier : choisis-en un avec « Autre dossier… »")
            empty.setObjectName("Muted")
            self.row.addWidget(empty)
            empty.show()
            return
        for index, part in enumerate(parts):
            if index:
                sep = QLabel("›")
                sep.setObjectName("CrumbSep")
                self.row.addWidget(sep)
                sep.show()
            chip = QLabel(part)
            chip.setObjectName("CrumbActive" if index == len(parts) - 1 else "Crumb")
            self.row.addWidget(chip)
            chip.show()  # ajouté à un widget déjà visible : à afficher explicitement


# --- aperçus de fichiers --------------------------------------------------------------------------


@lru_cache(maxsize=256)
def _preview_bytes(path: str, mtime: float, size: int) -> bytes | None:
    """Aperçu JPEG d'un PDF, AI ou PSD (mis en cache tant que le fichier ne change pas)."""
    from tribin.extract import extract

    try:
        info = extract(Path(path))
    except Exception:
        return None
    if info.images:
        return info.images[0]
    if Path(path).suffix.lower() in {".pdf", ".ai"}:
        from tribin.extract.pdf import render_first_page

        return render_first_page(Path(path))
    return None


def thumbnail(path: Path, width: int, height: int | None = None) -> QPixmap:
    """Miniature d'une image, aperçu d'un PDF/AI/PSD, sinon l'icône du type de fichier."""
    height = height or width
    suffix = path.suffix.lower()
    pix = QPixmap()
    if suffix in IMAGE_EXT and path.exists():
        pix = QPixmap(str(path))
    elif suffix in PREVIEW_EXT and path.exists():
        stat = path.stat()
        data = _preview_bytes(str(path), stat.st_mtime, stat.st_size)
        if data:
            pix.loadFromData(data)
    if not pix.isNull():
        return pix.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    side = min(width, height)
    return QFileIconProvider().icon(QFileInfo(str(path))).pixmap(side, side)
