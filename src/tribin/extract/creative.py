"""Fichiers créatifs : PSD (miniature + calques), AI (tentative PDF). INDD, AEP, vidéos : métadonnées seules."""

from __future__ import annotations

from pathlib import Path

from tribin.extract.image import to_jpeg_thumbnail
from tribin.models import FileInfo


def extract_psd(path: Path, info: FileInfo) -> None:
    from psd_tools import PSDImage

    psd = PSDImage.open(str(path))
    info.metadata["dimensions"] = f"{psd.width}x{psd.height}"
    layers = [layer.name for layer in psd][:30]
    if layers:
        info.metadata["calques"] = ", ".join(layers)[:400]
        info.text = "Calques : " + ", ".join(layers)
    image = None
    try:
        image = psd.thumbnail()  # vignette intégrée : rapide
    except Exception:
        image = None
    if image is None:
        image = psd.composite()
    if image is not None:
        info.images.append(to_jpeg_thumbnail(image))


def extract_ai(path: Path, info: FileInfo) -> None:
    """La plupart des fichiers Illustrator sont compatibles PDF ; sinon, métadonnées seules."""
    with open(path, "rb") as fh:
        head = fh.read(1024)
    if b"%PDF" not in head:
        info.metadata["format"] = "Illustrator (non compatible PDF)"
        return
    from tribin.extract.pdf import extract_pdf

    extract_pdf(path, info)
