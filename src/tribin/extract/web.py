"""Pages web et données structurées : HTML, MHTML (page enregistrée), XML, SVG, JSON, carnets Jupyter, liens .webloc.

Une page enregistrée pèse souvent plusieurs Mo (scripts, styles, images intégrées) : on n'en garde que ce qu'un humain
lit — titre, description, intertitres, texte visible.
"""

from __future__ import annotations

import email
import json
import re
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from tribin.extract.text import decode, redact_secrets
from tribin.models import FileInfo

MAX_CHARS = 4000
MAX_BYTES = 8 * 1024 * 1024  # au-delà, le début du fichier suffit
SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "object", "canvas"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th",
              "header", "footer", "main", "nav", "aside", "blockquote", "pre", "dt", "dd", "figcaption", "label"}
SCRIPT_TYPES = {"", "text/javascript", "application/javascript", "module", "text/babel", "application/ecmascript"}
MAX_EMBEDDED = 2 * 1024 * 1024  # par bloc de données intégré
THIN_PAGE = 200  # moins de caractères visibles : page construite en JavaScript, on regarde ses blocs de données
_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\$\{[^}]*\}")  # champs d'un gabarit pas encore rempli : « {{ titre }} »
_SPACES = re.compile(r"[ \t\r\f\v ]+")


class _PageText(HTMLParser):
    """Titre, métadonnées, intertitres et texte visible d'une page HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.headings: list[str] = []
        self.parts: list[str] = []
        self._skip = 0
        self._in_title = False
        self._heading: list[str] | None = None
        self._size = 0
        # blocs de données (gabarit, JSON) d'une page qui se construit en JavaScript : son vrai contenu est souvent là
        self.embedded: list[str] = []
        self._capture: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and attrs.get("type", "").lower() not in SCRIPT_TYPES or tag == "template":
            self._capture = []
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key in ("description", "og:title", "og:description", "og:site_name", "keywords", "author") \
                    and attrs.get("content"):
                self.meta.setdefault(key, attrs["content"].strip()[:300])
        if tag in SKIPPED_TAGS:
            self._skip += 1
        if tag in ("h1", "h2", "h3") and not self._skip:
            self._heading = []
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "img" and attrs.get("alt") and not self._skip:
            self.parts.append(f" {attrs['alt']} ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "template") and self._capture is not None:
            block = "".join(self._capture).strip()
            if block:
                self.embedded.append(block)
            self._capture = None
        if tag == "title":
            self._in_title = False
        if tag in SKIPPED_TAGS and self._skip:
            self._skip -= 1
        if tag in ("h1", "h2", "h3") and self._heading is not None:
            text = " ".join(_PLACEHOLDER.sub(" ", "".join(self._heading)).split())
            if text and len(self.headings) < 15:
                self.headings.append(text[:120])
            self._heading = None
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._capture is not None and sum(map(len, self._capture)) < MAX_EMBEDDED:
            self._capture.append(data)
        if self._in_title:
            self.title += data
            return
        if self._skip or self._size > MAX_CHARS * 4:
            return
        self.parts.append(data)
        self._size += len(data)
        if self._heading is not None:
            self._heading.append(data)

    def text(self) -> str:
        lines = (_SPACES.sub(" ", _PLACEHOLDER.sub(" ", line)).strip() for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if any(c.isalnum() for c in line))  # pas les lignes « · · »


def _embedded_text(block: str, depth: int) -> tuple[int, str, dict[str, str]]:
    """Contenu d'un bloc de données, avec sa priorité : 2 pour du HTML (éventuellement dans une chaîne JSON),
    1 pour des phrases tirées de données JSON, 0 si rien de lisible."""
    try:
        value = json.loads(block)
    except ValueError:
        value = block
    if isinstance(value, str):
        return (2, *html_summary(value, depth + 1)) if "<" in value else (0, "", {})
    # des phrases (titre, description…), pas des identifiants, types MIME ni données encodées
    sentences = [line for line in _flatten(value)
                 if " " in line.split(" : ", 1)[-1] and sum(c.isalpha() for c in line) > 0.6 * len(line)]
    return (1 if sentences else 0), "\n".join(sentences), {}


def html_summary(markup: str, depth: int = 0) -> tuple[str, dict[str, str]]:
    """Texte lisible d'une page HTML (titre et description en tête) et ses métadonnées."""
    parser = _PageText()
    parser.feed(markup)
    parser.close()
    if len(parser.text()) < THIN_PAGE and parser.embedded and depth < 2:
        found = [_embedded_text(block, depth) for block in parser.embedded]
        _, text, meta = max(found, key=lambda found: (found[0], len(found[1])))
        if len(text) > len(parser.text()):
            return text[:MAX_CHARS], meta
    meta: dict[str, str] = {}
    title = " ".join(parser.title.split()) or parser.meta.get("og:title", "")
    if title:
        meta["titre"] = title[:200]
    for key, label in (("og:site_name", "site"), ("author", "auteur")):
        if parser.meta.get(key):
            meta[label] = parser.meta[key][:120]
    head = []
    if title:
        head.append(f"Titre : {title}")
    description = parser.meta.get("description") or parser.meta.get("og:description")
    if description:
        head.append(f"Description : {description}")
    if parser.meta.get("keywords"):
        head.append(f"Mots-clés : {parser.meta['keywords']}")
    if parser.headings:
        head.append("Intertitres : " + " | ".join(parser.headings))
    body = parser.text()
    return "\n".join([*head, "", body] if body else head).strip()[:MAX_CHARS], meta


def _read(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(MAX_BYTES)


def _decode_html(raw: bytes) -> str:
    match = _CHARSET.search(raw[:4096])
    if match:
        try:
            return raw.decode(match.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    return decode(raw)


def extract_html(path: Path, info: FileInfo) -> None:
    info.text, meta = html_summary(_decode_html(_read(path)))
    info.metadata.update(meta)


def extract_mhtml(path: Path, info: FileInfo) -> None:
    """Page web enregistrée « en un seul fichier » (.mht, .mhtml) : la partie HTML du message MIME."""
    message = email.message_from_bytes(_read(path), policy=policy.default)
    for part in message.walk():
        if part.get_content_type() == "text/html":
            info.text, meta = html_summary(part.get_content())
            info.metadata.update(meta)
            break
    if message.get("Snapshot-Content-Location"):
        info.metadata["adresse"] = str(message["Snapshot-Content-Location"])[:200]


def _xml_text(raw: bytes) -> str:
    """Le texte d'un document XML, sans les balises (tolère un XML mal formé)."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return " ".join(re.sub(r"<[^>]+>", " ", decode(raw)).split())
    words = (" ".join(t.split()) for t in root.itertext())
    return "\n".join(w for w in words if w)


def extract_xml(path: Path, info: FileInfo) -> None:
    raw = _read(path)
    match = re.search(rb"<([A-Za-z_][\w:.-]*)", re.sub(rb"<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>", b"", raw[:4096],
                                                       flags=re.S))
    if match:
        info.metadata["racine"] = match.group(1).decode("ascii", "replace").split(":")[-1]
    info.text = redact_secrets(_xml_text(raw))[:MAX_CHARS]


def extract_svg(path: Path, info: FileInfo) -> None:
    """Dessin vectoriel : son titre, sa description et les textes qu'il contient."""
    raw = _read(path)
    size = re.search(rb'<svg[^>]*\bwidth="([\d.]+)[^"]*"[^>]*\bheight="([\d.]+)', raw[:4096])
    if size:
        info.metadata["dimensions"] = f"{size.group(1).decode()}x{size.group(2).decode()}"
    info.text = _xml_text(raw)[:MAX_CHARS]


def _flatten(value, prefix: str = "", out: list[str] | None = None, limit: int = 300) -> list[str]:
    """Paires « clé : valeur » d'un document JSON (valeurs courtes), dans l'ordre du fichier."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(item, f"{prefix}.{key}" if prefix else str(key), out, limit)
    elif isinstance(value, list):
        for item in value[:20]:
            _flatten(item, prefix, out, limit)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        if text and len(text) <= 300:
            out.append(f"{prefix} : {text}" if prefix else text)
    return out


def extract_json(path: Path, info: FileInfo) -> None:
    raw = decode(_read(path))
    try:
        data = json.loads(raw)
    except ValueError:
        info.text = redact_secrets(raw)[:MAX_CHARS]
        return
    info.text = redact_secrets("\n".join(_flatten(data)))[:MAX_CHARS]


def extract_notebook(path: Path, info: FileInfo) -> None:
    """Carnet Jupyter : le texte des cellules (Markdown d'abord, puis le code)."""
    data = json.loads(decode(_read(path)))
    cells = data.get("cells", [])
    sources = {"markdown": [], "code": []}
    for cell in cells:
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else str(source)
        if cell.get("cell_type") in sources and source.strip():
            sources[cell["cell_type"]].append(source.strip())
    info.metadata["cellules"] = str(len(cells))
    info.text = redact_secrets("\n\n".join(sources["markdown"] + sources["code"]))[:MAX_CHARS]


def extract_webloc(path: Path, info: FileInfo) -> None:
    """Raccourci web macOS (.webloc, liste de propriétés) : l'adresse."""
    import plistlib

    with open(path, "rb") as fh:
        url = plistlib.load(fh).get("URL", "")
    if url:
        info.metadata["adresse"] = url[:300]
        info.text = f"Lien vers : {url}"
