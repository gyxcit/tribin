from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fakes import fixed

from tribin.convention.loader import load_convention
from tribin.engine.proposer import ProposeContext, normalize_rel, propose
from tribin.extract import extract
from tribin.llm.base import LLMError

NOEL = "ACME/2026/2026-042_Campagne-Noel"


@pytest.fixture
def sb(sandbox_dir: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "sb"
    shutil.copytree(sandbox_dir, dest)
    return dest


def run(sb: Path, llm, name: str = "scan0042.pdf"):
    ctx = ProposeContext(root=sb / "root", convention=load_convention(sb / "convention.yaml"), llm=llm)
    return propose(extract(sb / "inbox" / name), ctx), llm


def test_name_built_by_code_from_folder(sb):
    p, llm = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", client="ACME", date="2026-10-12",
                           description="Devis impression affiches", confidence=0.86, reasoning="Devis imprimeur"))
    assert p.target_folder == f"{NOEL}/06_Admin" and not p.folder_is_new
    assert p.new_name == "2026-10-12_ACME_2026-042_Devis-impression-affiches.pdf"
    assert p.fields.category == "06_Admin" and p.fields.project_code == "2026-042"
    assert not p.needs_review and not p.warnings
    prompt = llm.prompts[0]
    assert "Nom d'origine : scan0042.pdf" in prompt and "DEVIS" in prompt
    assert f"{NOEL}/06_Admin" in prompt  # dossiers candidats
    assert "_PROJET_EN_COURS" not in prompt and "Rushes" not in prompt  # zones exclues jamais proposées


def test_unknown_client_warns(sb):
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", client="ZORG", description="Devis"))
    assert any("Client inconnu" in w for w in p.warnings)


def test_low_confidence_needs_review(sb):
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.4))
    assert p.needs_review


@pytest.mark.parametrize("folder", ["../../etc", "/etc/passwd", "C:/Windows", f"{NOEL}/../../../.."])
def test_escape_outside_root_refused(sb, folder):
    p, _ = run(sb, fixed(target_folder=folder, description="Devis"))
    assert p.manual or not p.target_folder.startswith("..")
    assert ".." not in p.target_folder


def test_excluded_zone_refused(sb):
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/03_Execution/_PROJET_EN_COURS", description="Devis"))
    assert p.manual


def test_new_folder_flagged(sb):
    p, _ = run(sb, fixed(target_folder="ACME/2026/2026-099_Nouveau-Projet/06_Admin", folder_is_new=True,
                         description="Devis", confidence=0.9))
    assert p.folder_is_new and any("Création de dossier" in w for w in p.warnings)
    p2, _ = run(sb, fixed(target_folder="Divers/Bazar", description="Devis", confidence=0.9))
    assert p2.folder_is_new and p2.confidence <= 0.5


def test_collision_adds_suffix(sb):
    target = sb / "root" / NOEL / "06_Admin" / "2026-10-12_ACME_2026-042_Devis.pdf"
    target.write_text("existant")
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", date="2026-10-12", description="devis"))
    assert p.new_name == "2026-10-12_ACME_2026-042_devis_2.pdf"


def test_llm_error_gives_manual(sb):
    p, _ = run(sb, fixed(error=LLMError("réseau coupé")))
    assert p.manual and p.new_name == "scan0042.pdf" and "réseau coupé" in p.reasoning


def test_version_taken_from_original_name(sb):
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/02_Creation", description="Affiche Noel"), "affiche_noel_v2.psd")
    assert p.new_name.endswith("_v02.psd")


def test_image_sent_to_llm(sb):
    _, llm = run(sb, fixed(target_folder=f"{NOEL}/05_Sources", description="Logo"), "logo_acme_HD.png")
    assert llm.images[0] and "Une image du fichier est jointe." in llm.prompts[0]


def test_alternatives_named(sb):
    from tribin.models import LLMAlternative

    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis",
                         alternatives=[LLMAlternative(target_folder=f"{NOEL}/01_Brief", description="Brief", reasoning="r")]))
    assert p.alternatives[0].target_folder == f"{NOEL}/01_Brief"
    assert "_Brief" in p.alternatives[0].new_name


def test_normalize_rel():
    assert normalize_rel("./A\\B/") == "A/B"
    assert normalize_rel("../A") is None
    assert normalize_rel("/A") is None
    assert normalize_rel("C:\\A") is None
