"""Icône de la corbeille dessinée par le code (avec pastille du nombre de fichiers en attente)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = QColor("#2f6fdf")


def bin_pixmap(size: int = 64, count: int = 0, color: QColor = ACCENT) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64
    p.setPen(QPen(color.darker(130), 3 * s))
    p.setBrush(QBrush(color))
    body = QPainterPath()
    body.moveTo(QPointF(14 * s, 20 * s))
    body.lineTo(QPointF(50 * s, 20 * s))
    body.lineTo(QPointF(46 * s, 58 * s))
    body.lineTo(QPointF(18 * s, 58 * s))
    body.closeSubpath()
    p.drawPath(body)
    p.drawRoundedRect(QRectF(10 * s, 12 * s, 44 * s, 7 * s), 2 * s, 2 * s)
    p.drawRect(QRectF(26 * s, 7 * s, 12 * s, 5 * s))
    p.setPen(QPen(QColor("white"), 2.5 * s))
    for x in (25, 32, 39):
        p.drawLine(QPointF(x * s, 27 * s), QPointF(x * s, 51 * s))
    if count:
        text = str(count) if count < 100 else "99+"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e5484d"))
        p.drawEllipse(QRectF(34 * s, 30 * s, 30 * s, 30 * s))
        p.setPen(QColor("white"))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int((16 if count < 10 else 12) * s))
        p.setFont(font)
        p.drawText(QRectF(34 * s, 30 * s, 30 * s, 30 * s), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pix


def bin_icon(count: int = 0) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        icon.addPixmap(bin_pixmap(size, count))
    return icon
