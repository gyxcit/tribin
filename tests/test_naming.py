from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tribin.convention.loader import Naming
from tribin.convention.naming import (
    build_name,
    clean_segment,
    extract_version,
    fit_to_path,
    is_valid_name,
    split_extension,
    unique_name,
)
from tribin.models import NameFields

NAMING = Naming(versioned_categories=["02_Creation"])


def fields(**kw) -> NameFields:
    base = dict(date=date(2026, 10, 12), client="ACME", project_code="2026-042", description="Devis impression")
    base.update(kw)
    return NameFields(**base)


def test_nominal():
    assert build_name(fields(), NAMING, ".PDF") == "2026-10-12_ACME_2026-042_Devis-impression.pdf"


def test_version_formatted():
    assert build_name(fields(version=3), NAMING, ".psd") == "2026-10-12_ACME_2026-042_Devis-impression_v03.psd"


def test_empty_fields_remove_segment_entirely():
    name = build_name(fields(client=None, project_code=None, version=None), NAMING, ".pdf")
    assert name == "2026-10-12_Devis-impression.pdf"
    assert "__" not in name and "_v" not in name


def test_missing_date_uses_fallback():
    assert build_name(fields(date=None), NAMING, ".pdf", fallback_date=date(2025, 1, 2)).startswith("2025-01-02_")


def test_missing_date_without_fallback_drops_segment():
    assert build_name(fields(date=None), NAMING, ".pdf") == "ACME_2026-042_Devis-impression.pdf"


def test_accents_removed():
    assert build_name(fields(description="Créa Noël été"), NAMING, ".pdf").endswith("_Crea-Noel-ete.pdf")


def test_accents_kept_when_not_ascii_only():
    naming = NAMING.model_copy(update={"ascii_only": False})
    assert build_name(fields(description="Créa Noël"), naming, ".pdf").endswith("_Créa-Noël.pdf")


def test_emojis_removed():
    assert build_name(fields(description="Affiche 🎄 Noël ✨"), NAMING, ".png").endswith("_Affiche-Noel.png")


@pytest.mark.parametrize("bad", ['<', '>', ':', '"', '/', '\\', '|', '?', '*', '\x00', '\x1f'])
def test_forbidden_chars_removed(bad):
    name = build_name(fields(description=f"Devis{bad}final"), NAMING, ".pdf")
    assert bad not in name
    assert is_valid_name(name)


def test_separator_inside_segment_becomes_word_separator():
    assert build_name(fields(description="devis_imprimeur  final"), NAMING, ".pdf").endswith("_devis-imprimeur-final.pdf")


def test_no_trailing_dot_or_space():
    name = build_name(fields(client=None, project_code=None, date=None, description="Rapport. "), NAMING, "")
    assert name == "Rapport"


def test_long_name_truncates_description_first():
    name = build_name(fields(description="mot " * 80), NAMING, ".pdf")
    assert len(name) <= NAMING.max_length
    assert name.startswith("2026-10-12_ACME_2026-042_mot-mot")
    assert name.endswith(".pdf")
    assert not name[:-4].endswith(("-", "_"))


def test_long_name_keeps_version():
    name = build_name(fields(description="mot " * 80, version=2), NAMING, ".pdf")
    assert name.endswith("_v02.pdf") and len(name) <= NAMING.max_length


def test_compound_extension_kept():
    assert split_extension("archive.TAR.GZ") == ("archive", ".TAR.GZ")
    assert build_name(fields(), NAMING, ".TAR.GZ").endswith("_Devis-impression.tar.gz")


def test_no_extension():
    assert split_extension("Makefile") == ("Makefile", "")
    assert split_extension(".bashrc") == (".bashrc", "")
    assert build_name(fields(), NAMING, "") == "2026-10-12_ACME_2026-042_Devis-impression"


def test_extension_case_kept_when_configured():
    naming = NAMING.model_copy(update={"lowercase_extension": False})
    assert build_name(fields(), naming, ".PDF").endswith(".PDF")


@pytest.mark.parametrize("reserved", ["CON", "prn", "Aux", "NUL", "COM1", "lpt9"])
def test_windows_reserved_names(reserved):
    name = build_name(NameFields(description=reserved), NAMING, ".txt")
    assert split_extension(name)[0].upper() != reserved.upper()
    assert is_valid_name(name)
    assert not is_valid_name(f"{reserved}.txt")


def test_empty_description_gives_safe_name():
    assert build_name(NameFields(description="🎄🎄"), NAMING, ".pdf") == "fichier.pdf"


def test_full_path_too_long_shortens_description():
    deep = Path("Z:/Clients") / ("d" * 170)
    name, warnings = fit_to_path(fields(description="description vraiment très longue " * 3), NAMING, ".pdf", deep)
    assert len(str(deep)) + 1 + len(name) <= 250
    assert warnings and "raccourci" in warnings[0]


def test_full_path_too_long_warns_when_impossible():
    deep = Path("Z:/Clients") / ("d" * 240)
    _, warnings = fit_to_path(fields(), NAMING, ".pdf", deep)
    assert warnings and "trop long" in warnings[0]


@pytest.mark.parametrize("name,expected", [
    ("affiche_v2.psd", 2), ("affiche_V02.psd", 2), ("affiche-v3.ai", 3), ("visuel_3.jpg", 3),
    ("affiche version 4.pdf", 4), ("affiche_final.psd", None), ("IMG_3381.jpg", None),
    ("scan0042.pdf", None), ("Facture_F2026-118.pdf", None), ("Planning_site_v2.xlsx", 2),
])
def test_extract_version(name, expected):
    assert extract_version(name) == expected


def test_unique_name_case_insensitive():
    assert unique_name("Devis.pdf", {"devis.pdf"}) == "Devis_2.pdf"
    assert unique_name("Devis.pdf", {"devis.pdf", "DEVIS_2.PDF"}) == "Devis_3.pdf"
    assert unique_name("a.tar.gz", {"a.tar.gz"}) == "a_2.tar.gz"
    assert unique_name("Libre.pdf", {"devis.pdf"}) == "Libre.pdf"


def test_unique_name_unicode_forms():
    nfd = "Été.pdf"  # « Été.pdf » décomposé (macOS)
    assert unique_name("Été.pdf", {nfd}) == "Été_2.pdf"


def test_clean_segment_collapses_separators():
    assert clean_segment("  Campagne   --  Noël ", NAMING) == "Campagne-Noel"
