"""Extraction de contenu : extract(path) -> FileInfo, aiguillage par type de fichier (section 6.2).

Chaque extracteur a 10 secondes au plus ; en cas d'échec on revient aux métadonnées seules, sans planter.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path

from tribin.convention.naming import split_extension
from tribin.models import FileInfo

log = logging.getLogger(__name__)

MAX_TEXT = 4000
TIMEOUT_S = 10.0
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tribin-extract")

mimetypes.add_type("image/vnd.adobe.photoshop", ".psd")
mimetypes.add_type("application/x-indesign", ".indd")
mimetypes.add_type("application/postscript", ".ai")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("image/heic", ".heic")


def file_id_for(path: Path, st: os.stat_result) -> str:
    """Identifiant stable d'un fichier : chemin + taille + date de modification."""
    raw = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8", "surrogatepass")
    return "f_" + hashlib.sha1(raw).hexdigest()[:16]


def base_info(path: Path) -> FileInfo:
    """Métadonnées toujours disponibles (nom, extension, taille, dates, dossier, type MIME)."""
    path = Path(path)
    st = path.stat()
    _, ext = split_extension(path.name)
    created = getattr(st, "st_birthtime", None) or st.st_ctime
    return FileInfo(
        file_id=file_id_for(path, st),
        path=str(Path(os.path.abspath(path))),
        name=path.name,
        extension=ext.lower(),
        size=st.st_size,
        created=datetime.fromtimestamp(min(created, st.st_mtime)).astimezone(),
        modified=datetime.fromtimestamp(st.st_mtime).astimezone(),
        origin_folder=str(Path(os.path.abspath(path)).parent),
        mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def _extractor_for(ext: str) -> Callable[[Path, FileInfo], None] | None:
    from tribin.extract import creative, image, office, pdf, text

    table: dict[str, Callable[[Path, FileInfo], None]] = {
        ".txt": text.extract_text, ".md": text.extract_text, ".csv": text.extract_text,
        ".pdf": pdf.extract_pdf,
        ".docx": office.extract_docx, ".xlsx": office.extract_xlsx, ".xlsm": office.extract_xlsx,
        ".pptx": office.extract_pptx,
        ".psd": creative.extract_psd, ".ai": creative.extract_ai,
    }
    for img_ext in image.IMAGE_EXTENSIONS:
        table[img_ext] = image.extract_image
    return table.get(ext)


def extract(path: Path, timeout: float = TIMEOUT_S) -> FileInfo:
    """Extrait les informations d'un fichier. Ne lève pas d'exception pour un contenu illisible."""
    info = base_info(path)
    extractor = _extractor_for(info.extension)
    if extractor is None:
        return info
    work = info.model_copy(deep=True)
    future = _POOL.submit(extractor, Path(path), work)
    try:
        future.result(timeout=timeout)
    except FutureTimeout:
        info.extraction_error = f"Extraction trop longue (> {timeout:.0f} s) : métadonnées seules."
        log.warning("extraction timeout: %s", path)
        return info
    except Exception as exc:  # fichier corrompu, format inattendu…
        info.extraction_error = f"Contenu illisible ({type(exc).__name__}) : métadonnées seules."
        log.warning("extraction failed for %s: %s", path, exc)
        return info
    work.text = work.text[:MAX_TEXT]
    return work
