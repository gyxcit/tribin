from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import pytest
from fakes import FakeLLM

from tribin.convention.loader import load_convention
from tribin.db import Database
from tribin.engine.candidates import select_candidates
from tribin.engine.clients import detect_client
from tribin.extract import extract
from tribin.mapping.infer import infer_convention
from tribin.mapping.profiles import (
    FolderDescription,
    FolderDescriptions,
    describe_profiles,
    detect_patterns,
    light_update,
    load_profiles,
    save_profiles,
)
from tribin.mapping.scanner import _scandir, scan_root


@pytest.fixture(scope="module")
def expected(sandbox_dir: Path) -> list[dict]:
    with open(sandbox_dir / "expected.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_scan_is_fast_and_complete(sandbox_dir: Path):
    conv = load_convention(sandbox_dir / "convention.yaml")
    started = time.monotonic()
    profiles = scan_root(sandbox_dir / "root", conv)
    assert time.monotonic() - started < 10
    rels = {p.rel for p in profiles}
    assert "ACME/2026/2026-042_Campagne-Noel/06_Admin" in rels
    admin = next(p for p in profiles if p.rel == "ACME/2026/2026-042_Campagne-Noel/06_Admin")
    assert admin.file_count == 1 and admin.extensions == [".pdf"] and admin.patterns["date_format"] == "AAAA-MM-JJ"


def test_excluded_zones_never_traversed(sandbox_dir: Path):
    conv = load_convention(sandbox_dir / "convention.yaml")
    visited: list[str] = []

    def spy(path: Path) -> list[os.DirEntry]:
        visited.append(str(path))
        return _scandir(path)

    profiles = scan_root(sandbox_dir / "root", conv, scandir=spy)
    assert not any("_PROJET_EN_COURS" in v or "Rushes" in v for v in visited)
    assert not any("_PROJET_EN_COURS" in p.rel or "Rushes" in p.rel for p in profiles)


def test_internal_and_hidden_dirs_skipped(tmp_path: Path):
    for d in ("_TriBin/a_trier", "_Archive", "A/_versions", ".cache", "A/Film.fcpbundle", "A/B"):
        (tmp_path / d).mkdir(parents=True)
    rels = {p.rel for p in scan_root(tmp_path, load_convention(Path("convention.example.yaml")))}
    assert rels == {"A", "A/B"}


def test_depth_limit(tmp_path: Path):
    (tmp_path / "1/2/3/4").mkdir(parents=True)
    rels = {p.rel for p in scan_root(tmp_path, load_convention(Path("convention.example.yaml")), max_depth=2)}
    assert rels == {"1", "1/2"}


def test_detect_patterns():
    names = ["2026-10-12_ACME_Devis_v01.pdf", "2026-09-01_ACME_Brief_final.pdf", "notes.txt"]
    p = detect_patterns(names)
    assert p["date_format"] == "AAAA-MM-JJ" and p["date_position"] == "début" and p["separator"] == "_"
    assert "v01" in p["version_tokens"] and "final" in p["version_tokens"]


def test_storage_and_light_update(tmp_path: Path, sandbox_dir: Path):
    conv = load_convention(sandbox_dir / "convention.yaml")
    db = Database(tmp_path / "t.db")
    profiles = scan_root(sandbox_dir / "root", conv)
    profiles[0].description = "décrit"
    save_profiles(db, sandbox_dir / "root", profiles)
    loaded = load_profiles(db, sandbox_dir / "root")
    assert len(loaded) == len(profiles) and loaded[0].description == "décrit"
    fresh = scan_root(sandbox_dir / "root", conv)[1:]  # un dossier « disparu »
    added, removed = light_update(db, sandbox_dir / "root", fresh)
    assert removed == [profiles[0].rel] and not added


def test_describe_in_batches_of_30(sandbox_dir: Path):
    profiles = scan_root(sandbox_dir / "root", load_convention(sandbox_dir / "convention.yaml"))
    batches: list[int] = []

    def answer(prompt: str):
        rels = [line[2:].split(" | ")[0] for line in prompt.splitlines() if line.startswith("- ")]
        batches.append(len(rels))
        return FolderDescriptions(items=[FolderDescription(rel=r, description=f"desc {r}") for r in rels])

    assert describe_profiles(profiles, FakeLLM(answer)) == len(profiles)
    assert max(batches) <= 30 and len(batches) == -(-len(profiles) // 30)


def test_infer_convention(sandbox_dir: Path):
    conv = infer_convention(scan_root(sandbox_dir / "root", load_convention(sandbox_dir / "convention.yaml")))
    assert conv.structure.template == "{client}/{year}/{project}/{category}"
    assert len(conv.structure.categories) == 6
    assert {c.code for c in conv.clients} == {"ACME", "BRIOC", "VELOM"}
    assert conv.naming.date_format == "%Y-%m-%d" and conv.naming.template.startswith("{date}_")


def test_client_detection_is_precise(sandbox_dir: Path, expected):
    conv = load_convention(sandbox_dir / "convention.yaml")
    found = wrong = 0
    for row in expected:
        code = detect_client(extract(sandbox_dir / "inbox" / row["file"]), conv)
        if code:
            found += 1
            wrong += code != row["expected_folder"].split("/")[0]
    assert wrong == 0
    assert found >= 0.6 * len(expected)  # images sans texte : l'IA voit l'image


def test_candidates_contain_expected_folder(sandbox_dir: Path, expected):
    conv = load_convention(sandbox_dir / "convention.yaml")
    profiles = scan_root(sandbox_dir / "root", conv)
    hits = 0
    for row in expected:
        info = extract(sandbox_dir / "inbox" / row["file"])
        cands = select_candidates(info, profiles, conv, detect_client(info, conv))
        assert len(cands) <= 15
        hits += row["expected_folder"] in {c.rel for c in cands}
    assert hits >= 0.8 * len(expected), hits
