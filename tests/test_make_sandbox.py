from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml
from make_sandbox import MARKER, make_sandbox


def test_structure(sandbox_dir: Path):
    for name in ("convention.yaml", "expected.csv", "root", "inbox", MARKER):
        assert (sandbox_dir / name).exists(), name
    conv = yaml.safe_load((sandbox_dir / "convention.yaml").read_text(encoding="utf-8"))
    assert len(conv["clients"]) == 3
    assert len(conv["structure"]["categories"]) == 6


def test_expected_matches_inbox(sandbox_dir: Path):
    with open(sandbox_dir / "expected.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    inbox = {p.name for p in (sandbox_dir / "inbox").iterdir()}
    assert len(rows) == len(inbox) >= 35
    for row in rows:
        assert row["file"] in inbox
        folders = [row["expected_folder"], *filter(None, row["acceptable_folders"].split("|"))]
        for folder in folders:
            assert (sandbox_dir / "root" / folder).is_dir(), folder


def test_rerun_recreates_cleanly(tmp_path: Path):
    dest = tmp_path / "sb"
    make_sandbox(dest)
    (dest / "inbox" / "intrus.txt").write_text("x")
    make_sandbox(dest)
    assert not (dest / "inbox" / "intrus.txt").exists()


def test_refuses_foreign_folder(tmp_path: Path):
    dest = tmp_path / "pas_une_sandbox"
    dest.mkdir()
    (dest / "precieux.txt").write_text("ne pas effacer")
    with pytest.raises(SystemExit):
        make_sandbox(dest)
    assert (dest / "precieux.txt").exists()
