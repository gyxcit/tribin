"""Autres documents : OpenDocument (LibreOffice), RTF, EPUB, e-mails (.eml), Apple iWork (Pages, Numbers, Keynote),
anciens formats Office (.doc, .xls, .ppt, lecture approximative) et archives (liste des fichiers contenus)."""

from __future__ import annotations

import email
import io
import re
import tarfile
import zipfile
from email import policy
from pathlib import Path, PurePosixPath

from tribin.extract.image import to_jpeg_thumbnail
from tribin.extract.text import decode, redact_secrets
from tribin.extract.web import html_summary
from tribin.models import FileInfo

MAX_CHARS = 4000
MAX_ENTRIES = 60  # fichiers d'une archive montrés à l'IA


def _clip(parts: list[str]) -> str:
    return "\n".join(p.strip() for p in parts if p and p.strip())[:MAX_CHARS]


# --- OpenDocument ------------------------------------------------------------------------------


def extract_odf(path: Path, info: FileInfo) -> None:
    """Texte (.odt), classeur (.ods), présentation (.odp) : paragraphes et titres du contenu, titre des propriétés."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "meta.xml" in names:
            meta = ET.fromstring(zf.read("meta.xml"))
            for element in meta.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                if tag in ("title", "subject", "initial-creator") and (element.text or "").strip():
                    info.metadata[{"title": "titre", "subject": "sujet", "initial-creator": "auteur"}[tag]] = \
                        element.text.strip()[:200]
        root = ET.fromstring(zf.read("content.xml"))
    parts, total = [], 0
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in ("h", "p"):
            text = " ".join("".join(element.itertext()).split())
            if text:
                parts.append(text)
                total += len(text)
                if total >= MAX_CHARS:
                    break
    info.text = _clip(parts)


# --- RTF ---------------------------------------------------------------------------------------

_RTF_TOKEN = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)", re.I | re.S)
# Groupes qui ne contiennent pas de texte lisible (polices, couleurs, styles, images…)
_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "listtable", "listoverridetable", "rsidtbl", "generator", "pict",
             "object", "header", "footer", "xmlnstbl", "themedata", "colorschememapping", "latentstyles",
             "datastore", "mmathPr", "pgdsctbl", "filetbl", "revtbl", "info"}
_RTF_BREAKS = {"par": "\n", "line": "\n", "sect": "\n", "page": "\n", "row": "\n", "cell": " ", "tab": " "}


def rtf_to_text(rtf: str) -> str:
    """Texte d'un document RTF (sans bibliothèque : groupes ignorés, caractères \\'hh et \\uN décodés)."""
    out: list[str] = []
    stack: list[bool] = []  # pour chaque groupe ouvert : ignoré ?
    skip, uc_skip = False, 0
    for word, arg, hexa, symbol, brace, char in _RTF_TOKEN.findall(rtf):
        if brace == "{":
            stack.append(skip)
        elif brace == "}":
            skip = stack.pop() if stack else False
        elif word:
            if word in _RTF_SKIP:
                skip = True
            elif not skip:
                if word in _RTF_BREAKS:
                    out.append(_RTF_BREAKS[word])
                elif word == "u" and arg:
                    out.append(chr(int(arg) % 65536))
                    uc_skip = 1  # caractère de remplacement qui suit \uN
        elif symbol == "*":
            skip = True  # destination facultative « {\*\…} »
        elif skip:
            continue
        elif hexa:
            if uc_skip:
                uc_skip = 0
                continue
            out.append(bytes([int(hexa, 16)]).decode("cp1252", errors="replace"))
        elif symbol in ("\\", "{", "}"):
            out.append(symbol)
        elif symbol == "~":
            out.append(" ")
        elif char:
            if uc_skip:
                uc_skip = 0
                continue
            out.append(char)
    lines = (" ".join(line.split()) for line in "".join(out).splitlines())
    return "\n".join(line for line in lines if line)


def extract_rtf(path: Path, info: FileInfo) -> None:
    with open(path, "rb") as fh:
        raw = fh.read(2 * 1024 * 1024)
    rtf = raw.decode("latin-1")
    title = re.search(r"\{\\title ([^}]*)\}", rtf)
    if title:
        info.metadata["titre"] = rtf_to_text(title.group(1))[:200]
    info.text = rtf_to_text(rtf)[:MAX_CHARS]


# --- EPUB --------------------------------------------------------------------------------------


def extract_epub(path: Path, info: FileInfo) -> None:
    """Livre numérique : titre, auteur, puis le début du texte (premiers chapitres)."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
        opf = ET.fromstring(zf.read(opf_path))
        for element in opf.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag in ("title", "creator") and (element.text or "").strip():
                info.metadata.setdefault({"title": "titre", "creator": "auteur"}[tag], element.text.strip()[:200])
        manifest = {e.get("id"): e.get("href") for e in opf.iter() if e.tag.endswith("item")}
        spine = [manifest.get(e.get("idref")) for e in opf.iter() if e.tag.endswith("itemref")]
        base = PurePosixPath(opf_path).parent
        parts, total = [], 0
        for href in [h for h in spine if h][:8]:
            try:
                text, _ = html_summary(decode(zf.read(str(base / href))))
            except KeyError:
                continue
            parts.append(text)
            total += len(text)
            if total >= MAX_CHARS:
                break
    head = [f"Livre : {info.metadata['titre']}" if "titre" in info.metadata else "",
            f"Auteur : {info.metadata['auteur']}" if "auteur" in info.metadata else ""]
    info.text = _clip(head + parts)


# --- e-mails -----------------------------------------------------------------------------------


def extract_eml(path: Path, info: FileInfo) -> None:
    """Message enregistré (.eml) : objet, expéditeur, destinataires, date, corps et noms des pièces jointes."""
    with open(path, "rb") as fh:
        message = email.message_from_binary_file(fh, policy=policy.default)
    head = []
    for key, label in (("subject", "Objet"), ("from", "De"), ("to", "À"), ("date", "Date")):
        value = str(message.get(key, "") or "").strip()
        if value:
            head.append(f"{label} : {value[:300]}")
            if key in ("subject", "from", "date"):
                info.metadata[{"subject": "objet", "from": "expéditeur", "date": "date"}[key]] = value[:200]
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = body.get_content()
        text = html_summary(content)[0] if body.get_content_type() == "text/html" else content
    attachments = [part.get_filename() for part in message.iter_attachments() if part.get_filename()]
    if attachments:
        head.append("Pièces jointes : " + ", ".join(attachments[:20]))
    info.text = redact_secrets(_clip(head + ["", text]))


# --- Apple iWork -------------------------------------------------------------------------------


def extract_iwork(path: Path, info: FileInfo) -> None:
    """Pages, Numbers, Keynote : le texte de l'aperçu PDF intégré, sinon sa vignette.

    « .key » est aussi l'extension des clés privées : seul un document Keynote (une archive) est ouvert."""
    if not zipfile.is_zipfile(path):
        info.metadata["format"] = "non lu (pas un document iWork)"
        return
    with zipfile.ZipFile(path) as zf:
        names = {n.lower(): n for n in zf.namelist()}
        pdf = names.get("quicklook/preview.pdf")
        if pdf:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(zf.read(pdf)))
            info.metadata["pages"] = str(len(reader.pages))
            info.text = _clip([page.extract_text() or "" for page in reader.pages[:3]])
        if len(info.text) < 20:
            thumb = next((names[n] for n in ("preview.jpg", "quicklook/thumbnail.jpg", "preview-web.jpg",
                                             "quicklook/preview.jpg") if n in names), None)
            if thumb:
                from PIL import Image

                info.images.append(to_jpeg_thumbnail(Image.open(io.BytesIO(zf.read(thumb)))))


# --- anciens formats Office --------------------------------------------------------------------

# Latin-1 (« x\x00 ») et ponctuation typographique U+2010–U+203A (« ’ », « – », « … »)
_UTF16_RUN = re.compile(rb"(?:[\x20-\x7e\xa0-\xff]\x00|[\x10-\x3a]\x20){6,}")
_ANSI_RUN = re.compile(rb"[\x20-\x7e\xc0-\xff\x80-\x9f]{8,}")


def legacy_strings(raw: bytes) -> str:
    """Morceaux de texte lisibles d'un fichier binaire Office 97-2003 (UTF-16 et Windows-1252)."""
    runs = [m.decode("utf-16-le", errors="ignore") for m in _UTF16_RUN.findall(raw)]
    runs += [m.decode("cp1252", errors="ignore") for m in _ANSI_RUN.findall(raw)]
    seen, out = set(), []
    for run in runs:
        run = " ".join(run.split())
        letters = sum(c.isalpha() for c in run)
        # du vrai texte : surtout des lettres et au moins un espace (pas des noms de polices ni du code binaire)
        if len(run) < 8 or " " not in run or letters < 0.6 * len(run.replace(" ", "")) or run in seen:
            continue
        seen.add(run)
        out.append(run)
    return "\n".join(out)


def extract_legacy_office(path: Path, info: FileInfo) -> None:
    with open(path, "rb") as fh:
        raw = fh.read(4 * 1024 * 1024)
    info.text = redact_secrets(legacy_strings(raw))[:MAX_CHARS]
    if info.text:
        info.metadata["lecture"] = "approximative (ancien format Office)"


# --- archives ----------------------------------------------------------------------------------


def extract_archive(path: Path, info: FileInfo) -> None:
    """Archive .zip, .tar, .tar.gz… : le nombre de fichiers et leurs noms (sans rien décompresser)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            entries = [i.filename for i in zf.infolist() if not i.is_dir()]
    else:
        with tarfile.open(path) as tf:
            entries = [m.name for m in tf.getmembers() if m.isfile()]
    entries = [e for e in entries if not e.startswith(("__MACOSX/", ".")) and "/." not in e]
    info.metadata["fichiers"] = str(len(entries))
    shown = entries[:MAX_ENTRIES]
    more = f"\n… et {len(entries) - len(shown)} autres" if len(entries) > len(shown) else ""
    info.text = (f"Archive de {len(entries)} fichier{'s' if len(entries) > 1 else ''} :\n" + "\n".join(shown)
                 + more)[:MAX_CHARS]
