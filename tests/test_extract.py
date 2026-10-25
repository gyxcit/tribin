from __future__ import annotations

import time
from pathlib import Path

import pytest

import tribin.extract as extract_mod
from tribin.extract import extract


def test_every_sandbox_file_extracts(sandbox_dir: Path):
    for path in (sandbox_dir / "inbox").iterdir():
        info = extract(path)
        assert info.name == path.name
        assert info.size == path.stat().st_size
        assert info.extraction_error is None, (path.name, info.extraction_error)
        assert len(info.text) <= 4000


def test_pdf_text(sandbox_dir: Path):
    info = extract(sandbox_dir / "inbox" / "scan0042.pdf")
    assert "DEVIS" in info.text and "Acme" in info.text
    assert info.mime == "application/pdf"
    assert not info.images


def test_scanned_pdf_rendered_as_image(sandbox_dir: Path):
    info = extract(sandbox_dir / "inbox" / "Scan_20261003.pdf")
    assert info.text.strip() == ""
    assert info.images and info.images[0][:2] == b"\xff\xd8"  # JPEG
    assert info.metadata.get("scan") == "oui"


@pytest.mark.parametrize("name,needle", [
    ("Document1.docx", "brioche"), ("budget_campagne.xlsx", "Budget Noël 2026"),
    ("Presentation_pistes_creatives.pptx", "Pistes créatives"), ("notes.txt", "Equip Auto"),
    ("galette_etiquette_v3.ai", "Galette"),
])
def test_office_and_text(sandbox_dir: Path, name, needle):
    assert needle.lower() in extract(sandbox_dir / "inbox" / name).text.lower()


def test_image_thumbnail_and_exif(sandbox_dir: Path):
    info = extract(sandbox_dir / "inbox" / "IMG_3381.jpg")
    assert info.images and info.metadata.get("exif_Model") == "Canon EOS R6"


def test_psd_thumbnail(sandbox_dir: Path):
    info = extract(sandbox_dir / "inbox" / "affiche_noel_v1.psd")
    assert info.images


def test_metadata_only_formats(sandbox_dir: Path):
    info = extract(sandbox_dir / "inbox" / "catalogue_2026_maquette.indd")
    assert info.text == "" and not info.images and info.extension == ".indd"


def test_corrupted_file_falls_back(tmp_path: Path):
    bad = tmp_path / "casse.pdf"
    bad.write_bytes(b"%PDF-1.4 pas vraiment un pdf")
    info = extract(bad)
    assert info.extraction_error and info.size == bad.stat().st_size


def test_timeout_falls_back(tmp_path: Path, monkeypatch):
    slow = tmp_path / "lent.txt"
    slow.write_text("contenu")
    monkeypatch.setattr(extract_mod, "_extractor_for", lambda ext: lambda p, i: time.sleep(1.5))
    info = extract(slow, timeout=0.2)
    assert "trop longue" in (info.extraction_error or "")


def test_cp1252_text(tmp_path: Path):
    f = tmp_path / "ancien.txt"
    f.write_bytes("Devis été".encode("cp1252"))
    assert extract(f).text == "Devis été"


# --- formats ajoutés : pages web, données, documents, e-mails, archives -----------------------------


def test_html_visible_text_title_and_description(tmp_path: Path):
    page = tmp_path / "Stagio Traitement.html"
    page.write_text("<html><head><title>Stagio — Traitement</title><meta name='description' content='Analyse des "
                    "slides'><style>body{color:red}</style><script>var secret = 1;</script></head><body>"
                    "<h1>Présentation terminée</h1><p>Le traitement analyse vos slides.</p></body></html>",
                    encoding="utf-8")
    info = extract(page)
    assert info.metadata["titre"] == "Stagio — Traitement"
    assert "Description : Analyse des slides" in info.text and "Le traitement analyse vos slides." in info.text
    assert "Intertitres : Présentation terminée" in info.text
    assert "color:red" not in info.text and "secret" not in info.text


def test_html_built_by_javascript_reads_its_embedded_template(tmp_path: Path):
    """Page « Unpacking… » dont le vrai contenu est un gabarit HTML rangé dans un bloc de données."""
    import json

    inner = "<html><body><h1>{{ deckTitle }}</h1><p>Stagio. Le traitement analyse vos slides et votre discours.</p>"
    page = tmp_path / "bundle.html"
    page.write_text("<html><head><title>Bundled Page</title></head><body><div>Unpacking...</div>"
                    '<script type="__bundler/manifest">{"a1b2": {"mime": "font/woff2", "data": "H4sIAAAA"}}</script>'
                    f'<script type="__bundler/template">{json.dumps(inner)}</script></body></html>', encoding="utf-8")
    text = extract(page).text
    assert "Stagio. Le traitement analyse vos slides" in text
    assert "{{" not in text and "woff2" not in text and "Unpacking" not in text


def test_mhtml_xml_svg_json_notebook(tmp_path: Path):
    mht = tmp_path / "page.mhtml"
    mht.write_bytes(b"MIME-Version: 1.0\r\nSnapshot-Content-Location: https://exemple.fr/devis\r\n"
                    b'Content-Type: multipart/related; boundary="b"\r\n\r\n--b\r\nContent-Type: text/html; '
                    b"charset=utf-8\r\n\r\n<html><head><title>Devis ACME</title></head><body><p>Total 1200 euros</p>"
                    b"</body></html>\r\n--b--\r\n")
    info = extract(mht)
    assert info.metadata["titre"] == "Devis ACME" and "Total 1200 euros" in info.text
    assert info.metadata["adresse"] == "https://exemple.fr/devis"

    xml = tmp_path / "facture.xml"
    xml.write_text('<?xml version="1.0"?><Invoice><Seller>ACME</Seller><Total>42</Total></Invoice>')
    info = extract(xml)
    assert info.metadata["racine"] == "Invoice" and "ACME" in info.text

    svg = tmp_path / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"><title>Logo Stagio</title>'
                   "<text>Stagio</text></svg>")
    info = extract(svg)
    assert "Logo Stagio" in info.text and info.metadata["dimensions"] == "120x40"

    data = tmp_path / "commande.json"
    data.write_text('{"client": {"nom": "ACME Corp"}, "lignes": [{"article": "Affiches A2"}], "api_key": "sk-123"}')
    text = extract(data).text
    assert "client.nom : ACME Corp" in text and "lignes.article : Affiches A2" in text and "sk-123" not in text

    notebook = tmp_path / "analyse.ipynb"
    notebook.write_text('{"cells": [{"cell_type": "markdown", "source": ["# Analyse des ventes"]}, '
                        '{"cell_type": "code", "source": "import pandas"}]}')
    info = extract(notebook)
    assert info.text.startswith("# Analyse des ventes") and info.metadata["cellules"] == "2"


def test_opendocument_rtf_epub(tmp_path: Path):
    import zipfile

    odt = tmp_path / "compte-rendu.odt"
    with zipfile.ZipFile(odt, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("meta.xml", '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
                    ' xmlns:dc="http://purl.org/dc/elements/1.1/"><office:meta><dc:title>Réunion chantier</dc:title>'
                    "</office:meta></office:document-meta>")
        zf.writestr("content.xml", '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:'
                    'office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body>'
                    "<office:text><text:h>Ordre du jour</text:h><text:p>Planning <text:span>VELOM</text:span>"
                    "</text:p></office:text></office:body></office:document-content>")
    info = extract(odt)
    assert info.metadata["titre"] == "Réunion chantier" and info.text == "Ordre du jour\nPlanning VELOM"

    rtf = tmp_path / "lettre.rtf"
    rtf.write_bytes(rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}{\info{\title Lettre}}{\*\generator Word;}"
                    rb"Objet : r\'e9siliation\par Caf\u233?\par}")
    info = extract(rtf)
    assert info.text == "Objet : résiliation\nCafé" and info.metadata["titre"] == "Lettre"

    epub = tmp_path / "livre.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/>'
                    "</rootfiles></container>")
        zf.writestr("OEBPS/c.opf", '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Le Guide'
                    '</dc:title><dc:creator>R. L.</dc:creator></metadata><manifest><item id="c1" href="c1.xhtml"/>'
                    '</manifest><spine><itemref idref="c1"/></spine></package>')
        zf.writestr("OEBPS/c1.xhtml", "<html><body><p>Chapitre un : ranger ses papiers.</p></body></html>")
    info = extract(epub)
    assert info.metadata["titre"] == "Le Guide" and "Chapitre un : ranger ses papiers." in info.text


def test_eml_legacy_office_archive_and_secrets(tmp_path: Path, sandbox_dir: Path):
    import zipfile

    eml = tmp_path / "message.eml"
    eml.write_bytes("From: ACME <compta@acme.fr>\r\nTo: moi@exemple.fr\r\nSubject: Facture octobre\r\n"
                    "Date: Thu, 16 Oct 2026 10:00:00 +0200\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
                    "Bonjour, voici la facture.\r\nmot de passe: hunter2\r\n".encode("utf-8"))
    info = extract(eml)
    assert "Objet : Facture octobre" in info.text and "Bonjour, voici la facture." in info.text
    assert info.metadata["objet"] == "Facture octobre" and "hunter2" not in info.text

    doc = tmp_path / "ancien.doc"
    doc.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64 + "Compte rendu de la réunion ACME".encode("utf-16-le")
                    + b"\x00\x01\x02" * 20)
    info = extract(doc)
    assert "Compte rendu de la réunion ACME" in info.text and info.metadata["lecture"].startswith("approximative")

    archive = tmp_path / "livrables.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in ("Affiche_Noel.pdf", "sources/logo.ai", "__MACOSX/._logo.ai"):
            zf.writestr(name, "x")
    info = extract(archive)
    assert info.metadata["fichiers"] == "2" and "Affiche_Noel.pdf" in info.text and "__MACOSX" not in info.text

    keynote = tmp_path / "pitch.key"
    with zipfile.ZipFile(keynote, "w") as zf:
        pdf = next((sandbox_dir / "inbox").glob("*.pdf"))
        zf.writestr("QuickLook/Preview.pdf", pdf.read_bytes())
    assert extract(keynote).metadata["pages"]
    private_key = tmp_path / "serveur.key"  # même extension, mais une clé privée : jamais lue
    private_key.write_text("-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n")
    info = extract(private_key)
    assert info.text == "" and "MIIE" not in str(info.metadata)

    config = tmp_path / "settings.yaml"
    config.write_text("projet: Stagio\npassword: tres-secret\nAPI_KEY = abc\n")
    text = extract(config).text
    assert "projet: Stagio" in text and "tres-secret" not in text and "abc" not in text


def test_document_creation_date_in_metadata(tmp_path: Path):
    from sandbox_files import write_file

    write_file(tmp_path / "lettre.docx", {"kind": "docx", "title": "Lettre", "lines": ["Bonjour"], "mtime": "2024-03-05"})
    assert extract(tmp_path / "lettre.docx").metadata["date_creation_document"] == "2024-03-05"
    write_file(tmp_path / "plan.xlsx", {"kind": "xlsx", "sheets": {"Plan": [["a", 1]]}, "mtime": "2024-04-06"})
    assert extract(tmp_path / "plan.xlsx").metadata["date_creation_document"] == "2024-04-06"
    write_file(tmp_path / "deck.pptx", {"kind": "pptx", "slides": [("Titre", "Corps")], "mtime": "2024-05-07"})
    assert extract(tmp_path / "deck.pptx").metadata["date_creation_document"] == "2024-05-07"
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/CreationDate": "D:20240305100000+00'00'"})
    with open(tmp_path / "doc.pdf", "wb") as fh:
        writer.write(fh)
    assert extract(tmp_path / "doc.pdf").metadata["date_creation_document"] == "2024-03-05"
