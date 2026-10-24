"""Génère les icônes d'empaquetage (packaging/tribin.ico, .icns, .png) à partir du logo src/tribin/resources/logo.svg.

    uv run python scripts/make_icons.py

Le SVG est rendu par Qt (PySide6, option « ui »), puis Pillow écrit les formats Windows et macOS.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LOGO = REPO / "src" / "tribin" / "resources" / "logo.svg"
OUT = REPO / "packaging"


def render(size: int) -> Image.Image:
    """Rend le logo SVG en image RGBA de `size` pixels."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    _app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 — nécessaire au rendu Qt
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(LOGO)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = render(1024)
    # Les petites tailles sont rendues directement (plus nettes qu'une réduction de la grande image).
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [render(s) for s in sizes]
    frames[-1].save(OUT / "tribin.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    big.save(OUT / "tribin.icns")
    render(256).save(OUT / "tribin.png")
    print(f"Icônes écrites dans {OUT}")


if __name__ == "__main__":
    main()
