from __future__ import annotations

from pathlib import Path

import pytest

from tribin.convention.loader import ConventionError, load_convention, parse_convention
from tribin.convention.structure import fields_from_folder, folder_from_fields, matches_template
from tribin.models import NameFields

REPO = Path(__file__).resolve().parents[1]


def test_example_convention_loads():
    conv = load_convention(REPO / "convention.example.yaml")
    assert conv.category_codes()[0] == "01_Brief"
    assert conv.client_by_code("acme").code == "ACME"
    assert conv.naming.max_length == 120


def test_readable_errors():
    with pytest.raises(ConventionError) as err:
        parse_convention({"naming": {"template": "{date}_{inconnu}", "max_length": "beaucoup"}})
    text = str(err.value)
    assert "naming.template" in text and "inconnu" in text
    assert "naming.max_length" in text and "suggestion" in text


def test_duplicate_client_codes_refused():
    with pytest.raises(ConventionError):
        parse_convention({"clients": [{"code": "A"}, {"code": "a"}]})


def test_missing_file(tmp_path):
    with pytest.raises(ConventionError, match="introuvable"):
        load_convention(tmp_path / "absent.yaml")


def test_bad_yaml(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("naming:\n  template: [\n", encoding="utf-8")
    with pytest.raises(ConventionError, match="ligne"):
        load_convention(f)


def test_structure_roundtrip():
    conv = load_convention(REPO / "convention.example.yaml")
    fields = NameFields(client="ACME", project_code="2026-042", project_name="Campagne Noël", category="06_Admin")
    folder = folder_from_fields(fields, conv)
    assert folder == "ACME/2026/2026-042_Campagne-Noel/06_Admin"
    assert matches_template(folder, conv)
    assert fields_from_folder(folder, conv) == {"client": "ACME", "year": "2026", "project_code": "2026-042",
                                                "project_name": "Campagne-Noel", "category": "06_Admin"}
    assert not matches_template("ACME/2026/06_Admin", conv)
