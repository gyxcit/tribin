"""Phase 6 : détection des versions."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fakes import fixed
from PIL import Image

from tribin.service.bin import BinService, Validation
from tribin.service.config_store import AppConfig
from tribin.versions.detector import family, normalize_base

NOEL = "ACME/2026/2026-042_Campagne-Noel"
GALETTE = "BRIOC/2025/2025-031_Packaging-Galette"


@pytest.mark.parametrize("a,b", [
    ("affiche_noel_v1.psd", "affiche_noel_final.psd"),
    ("affiche_noel_v2.psd", "Affiche-Noel_V02.psd"),
    ("catalogue_2026_maquette.indd", "catalogue_2026_maquette (1).indd"),
    ("visuel_final_OK.jpg", "visuel.jpg"),
    ("Devis copie.pdf", "devis.pdf"),
    ("2026-10-12_logo_valide.png", "logo-def.png"),
])
def test_normalize_base_equal(a, b):
    assert normalize_base(a) == normalize_base(b) != ""


def test_families():
    assert family(".JPG") == family(".png") and family(".psd") != family(".jpg")


@pytest.fixture
def sb(settings, sandbox_dir: Path) -> Path:
    dest = settings.sandbox_dir / "copy"
    shutil.copytree(sandbox_dir, dest)
    return dest


def service(settings, sb: Path, folder: str, description: str) -> BinService:
    llm = fixed(target_folder=folder, description=description, confidence=0.9)
    svc = BinService(settings, provider_factory=lambda s, m=None: llm)
    svc.update_config(AppConfig(roots=[str(sb / "root")], convention_path=str(sb / "convention.yaml"), onboarding_done=True))
    return svc


def test_sandbox_series_recognized(settings, sb):
    svc = service(settings, sb, f"{NOEL}/02_Creation", "Affiche Noel")
    items = [svc.drop(sb / "inbox" / n) for n in ("affiche_noel_v1.psd", "affiche_noel_v2.psd", "affiche_noel_final.psd")]
    v1, v2, final = (svc.analyze(i.file_id).proposal for i in items)
    assert v1.new_name.endswith("_Affiche-Noel_v01.psd")
    assert v2.new_name.endswith("_Affiche-Noel_v02.psd") and any("Nouvelle version" in w for w in v2.warnings)
    assert final.new_name.endswith("_Affiche-Noel_v03.psd") and any("→ v03" in w for w in final.warnings)


def test_next_number_after_existing_versions(settings, sb):
    target = sb / "root" / NOEL / "02_Creation"
    for v in (1, 2, 3):
        shutil.copy(sb / "inbox" / "affiche_noel_v1.psd", target / f"2026-09-1{v}_ACME_2026-042_Affiche-Noel_v0{v}.psd")
    svc = service(settings, sb, f"{NOEL}/02_Creation", "Affiche Noel")
    p = svc.analyze(svc.drop(sb / "inbox" / "affiche_noel_final.psd").file_id).proposal
    assert p.new_name.endswith("_v04.psd") and len(p.older_versions) == 3


def test_older_versions_archived_with_simulation_and_undo(settings, sb):
    svc = service(settings, sb, f"{NOEL}/02_Creation", "Affiche Noel")
    first = svc.analyze(svc.drop(sb / "inbox" / "affiche_noel_v1.psd").file_id)
    svc.commit(svc.prepare([Validation(first.file_id, first.proposal.target_folder, first.proposal.new_name, "accepted")]))
    placed_v1 = sb / "root" / NOEL / "02_Creation" / first.proposal.new_name
    assert placed_v1.exists()

    second = svc.analyze(svc.drop(sb / "inbox" / "affiche_noel_v2.psd").file_id)
    assert second.proposal.older_versions == [str(placed_v1)]
    prepared = svc.prepare([Validation(second.file_id, second.proposal.target_folder, second.proposal.new_name, "accepted")])
    assert prepared.needs_confirmation  # déplacement des anciennes versions : simulation montrée
    assert [op.action for op in prepared.batch.ops] == ["mkdir", "move", "move"]
    assert prepared.report.ok
    result = svc.commit(prepared)
    archived = sb / "root" / NOEL / "02_Creation" / "_versions" / placed_v1.name
    assert archived.exists() and not placed_v1.exists()
    assert (sb / "root" / NOEL / "02_Creation" / second.proposal.new_name).exists()

    undo = svc.executor().undo(batch_id=result.batch_id)
    assert all(r["status"] == "undone" for r in undo)
    assert placed_v1.exists() and not (sb / "root" / NOEL / "02_Creation" / "_versions").exists()


def test_non_versioned_category_untouched(settings, sb):
    svc = service(settings, sb, f"{NOEL}/06_Admin", "Devis impression")
    p = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id).proposal
    assert "_v" not in p.new_name and not p.older_versions


def test_images_confirmed_by_perceptual_hash(settings, sb):
    svc = service(settings, sb, f"{GALETTE}/02_Creation", "Mockup packaging galette")
    v1 = svc.analyze(svc.drop(sb / "inbox" / "mockup_packaging_galette_v1.png").file_id)
    svc.commit(svc.prepare([Validation(v1.file_id, v1.proposal.target_folder, v1.proposal.new_name, "accepted")]))
    v2 = svc.analyze(svc.drop(sb / "inbox" / "mockup_packaging_galette_v2.png").file_id).proposal
    assert v2.new_name.endswith("_v02.png") and v2.older_versions
    # même nom mais image totalement différente : pas une version
    noise = sb / "inbox" / "mockup_packaging_galette_v3.png"
    Image.effect_noise((800, 600), 120).convert("RGB").save(noise)
    other = svc.analyze(svc.drop(noise).file_id).proposal
    assert not other.older_versions
