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


# Fichiers lus comme du texte brut : notes, données, sous-titres, agendas, contacts, configuration, code source.
# Jamais lus (le nom suffit) : .env, .pem, .p12, .kdbx… (secrets), et tout format absent des tables ci-dessous.
TEXT_EXTENSIONS = (
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log", ".tex", ".bib", ".srt", ".vtt", ".ics", ".vcf",
    ".url", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sql", ".css", ".scss", ".less",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".java", ".kt", ".swift", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".r", ".dart", ".scala", ".sh", ".bash",
    ".zsh", ".bat", ".cmd", ".ps1",
)
ARCHIVE_EXTENSIONS = (".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz")


def _extractor_for(ext: str) -> Callable[[Path, FileInfo], None] | None:
    from tribin.extract import creative, documents, image, office, pdf, text, web

    table: dict[str, Callable[[Path, FileInfo], None]] = {
        ".pdf": pdf.extract_pdf,
        ".docx": office.extract_docx, ".docm": office.extract_docx, ".xlsx": office.extract_xlsx,
        ".xlsm": office.extract_xlsx, ".pptx": office.extract_pptx, ".pptm": office.extract_pptx,
        ".doc": documents.extract_legacy_office, ".xls": documents.extract_legacy_office,
        ".ppt": documents.extract_legacy_office,
        ".odt": documents.extract_odf, ".ods": documents.extract_odf, ".odp": documents.extract_odf,
        ".odg": documents.extract_odf, ".rtf": documents.extract_rtf, ".epub": documents.extract_epub,
        ".eml": documents.extract_eml, ".pages": documents.extract_iwork, ".numbers": documents.extract_iwork,
        ".key": documents.extract_iwork,
        ".html": web.extract_html, ".htm": web.extract_html, ".xhtml": web.extract_html, ".shtml": web.extract_html,
        ".mht": web.extract_mhtml, ".mhtml": web.extract_mhtml, ".xml": web.extract_xml, ".svg": web.extract_svg,
        ".json": web.extract_json, ".ipynb": web.extract_notebook, ".webloc": web.extract_webloc,
        ".psd": creative.extract_psd, ".ai": creative.extract_ai,
    }
    for text_ext in TEXT_EXTENSIONS:
        table[text_ext] = text.extract_text
    for archive_ext in ARCHIVE_EXTENSIONS:
        table[archive_ext] = documents.extract_archive
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
