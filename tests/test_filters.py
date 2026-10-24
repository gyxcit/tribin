from __future__ import annotations

import os
from pathlib import Path

import pytest

from tribin.fs.filters import EXCLUDED_ZONE_MESSAGE, ExclusionMatcher, NotProcessable, check_processable, is_being_written

PATTERNS = ["**/_PROJET_EN_COURS/**", "**/Rushes/**"]


@pytest.mark.parametrize("rel,excluded", [
    ("ACME/2026/P/03_Execution/_PROJET_EN_COURS/a.indd", True),
    ("ACME/2026/P/03_Execution/_PROJET_EN_COURS", True),
    ("_PROJET_EN_COURS/x", True),
    ("VELOM/2026/P/05_Sources/rushes/clip.mp4", True),
    ("ACME/2026/P/03_Execution/a.pdf", False),
    ("ACME/Rushes-bis/a.pdf", False),
])
def test_exclusion_matcher(rel, excluded):
    assert ExclusionMatcher(PATTERNS).matches_rel(rel) is excluded


@pytest.mark.parametrize("name", [".DS_Store", "Thumbs.db", "desktop.ini", "~$Devis.docx", "a.tmp", "b.part",
                                  "c.crdownload", "d.pdf.tribin-partial"])
def test_system_files_refused(tmp_path: Path, name):
    f = tmp_path / name
    f.write_text("x")
    with pytest.raises(NotProcessable):
        check_processable(f)


def test_folders_and_packages_refused(tmp_path: Path):
    (tmp_path / "dossier").mkdir()
    (tmp_path / "Film.fcpbundle").mkdir()
    with pytest.raises(NotProcessable, match="dossier"):
        check_processable(tmp_path / "dossier")
    with pytest.raises(NotProcessable, match="paquet"):
        check_processable(tmp_path / "Film.fcpbundle")


def test_excluded_zone_refused(tmp_path: Path):
    f = tmp_path / "A" / "_PROJET_EN_COURS" / "x.indd"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    with pytest.raises(NotProcessable, match=EXCLUDED_ZONE_MESSAGE[:20]):
        check_processable(f, tmp_path, ExclusionMatcher(PATTERNS))


def test_symlink_refused(tmp_path: Path):
    target = tmp_path / "t.txt"
    target.write_text("x")
    link = tmp_path / "l.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques non autorisés")
    with pytest.raises(NotProcessable, match="lien"):
        check_processable(link)


def test_normal_file_accepted(tmp_path: Path):
    f = tmp_path / "Devis.pdf"
    f.write_text("x")
    check_processable(f, tmp_path, ExclusionMatcher(PATTERNS))


def test_stable_file_not_being_written(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert is_being_written(f, delay=0.05) is False
