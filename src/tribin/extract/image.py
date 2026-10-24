"""Images : métadonnées EXIF + miniature JPEG 1024 px envoyée à l'IA."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import ExifTags, Image

from tribin.models import FileInfo

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".gif", ".bmp")
THUMB_SIZE = 1024
EXIF_KEEP = {"Make", "Model", "DateTime", "DateTimeOriginal", "Artist", "Copyright", "ImageDescription", "Software"}


def to_jpeg_thumbnail(img: Image.Image, size: int = THUMB_SIZE) -> bytes:
    """Réduit l'image (côté max `size`) et la renvoie en JPEG."""
    img = img.copy()
    img.thumbnail((size, size))
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def extract_image(path: Path, info: FileInfo) -> None:
    with Image.open(path) as img:
        info.metadata["dimensions"] = f"{img.width}x{img.height}"
        try:
            exif = img.getexif()
            for tag_id, value in exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if name in EXIF_KEEP:
                    info.metadata[f"exif_{name}"] = str(value).strip("\x00 ")[:120]
        except Exception:
            pass
        info.images.append(to_jpeg_thumbnail(img))
