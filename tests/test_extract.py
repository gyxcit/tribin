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
