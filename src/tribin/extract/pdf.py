"""PDF : texte des 3 premières pages ; si aucun texte (scan), rendu de la page 1 en image."""

from __future__ import annotations

import logging
from pathlib import Path

from tribin.extract.image import to_jpeg_thumbnail
from tribin.models import FileInfo

log = logging.getLogger(__name__)

MAX_PAGES = 3
MAX_CHARS = 4000


def extract_pdf(path: Path, info: FileInfo) -> None:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    info.metadata["pages"] = str(len(reader.pages))
    meta = reader.metadata or {}
    title = getattr(meta, "title", None)
    if title:
        info.metadata["titre"] = str(title)[:200]
    parts: list[str] = []
    for page in reader.pages[:MAX_PAGES]:
        parts.append(page.extract_text() or "")
        if sum(len(p) for p in parts) >= MAX_CHARS:
            break
    text = "\n".join(p.strip() for p in parts).strip()
    info.text = text[:MAX_CHARS]
    if len(text) < 20:
        image = render_first_page(path)
        if image:
            info.images.append(image)
            info.metadata["scan"] = "oui"


def render_first_page(path: Path) -> bytes | None:
    """Rendu de la première page en JPEG (1024 px max) avec pypdfium2."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[0]
            width, height = page.get_size()
            scale = 1024 / max(width, height)
            pil = page.render(scale=scale).to_pil()
            return to_jpeg_thumbnail(pil)
        finally:
            pdf.close()
    except Exception as exc:
        log.warning("PDF render failed for %s: %s", path, exc)
        return None
