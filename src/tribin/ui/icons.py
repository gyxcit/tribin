"""Logo de TriBin (entonnoir : le désordre entre, l'ordre sort), avec pastille du nombre de fichiers en attente."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from tribin import resources

LOGO_SVG = Path(resources.__file__).with_name("logo.svg")
BADGE = QColor("#E5484D")


@lru_cache(maxsize=1)
def _renderer() -> QSvgRenderer:
    return QSvgRenderer(str(LOGO_SVG))


def logo_pixmap(size: int = 64, count: int = 0) -> QPixmap:
    """Logo à la taille demandée ; pastille rouge avec le nombre de fichiers en attente si `count` > 0."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _renderer().render(p, QRectF(0, 0, size, size))
    if count:
        text = str(count) if count < 100 else "99+"
        d = size * 0.52
        rect = QRectF(size - d, 0, d, d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BADGE)
        p.drawEllipse(rect)
        p.setPen(QColor("white"))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(6, int(d * (0.55 if count < 10 else 0.42))))
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pix


def app_icon(count: int = 0) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(size, count))
    return icon
