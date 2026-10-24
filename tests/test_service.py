from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fakes import fixed

from tribin.llm.base import LLMError
from tribin.safety import restore
from tribin.service.bin import BinError, BinService, Validation
from tribin.service.config_store import AppConfig

NOEL = "ACME/2026/2026-042_Campagne-Noel"


@pytest.fixture
def sb(settings, sandbox_dir: Path) -> Path:
    dest = settings.sandbox_dir / "copy"
    shutil.copytree(sandbox_dir, dest)
    return dest


def service(settings, sb: Path, llm=None, factory=None) -> BinService:
    llm = llm or fixed(target_folder=f"{NOEL}/06_Admin", date="2026-10-12", description="Devis impression",
                       confidence=0.9, reasoning="Devis de l'imprimeur")
    svc = BinService(settings, provider_factory=factory or (lambda s, m=None: llm))
    svc.update_config(AppConfig(roots=[str(sb / "root")], convention_path=str(sb / "convention.yaml"),
                                onboarding_done=True, privacy_accepted=True))
    return svc


def test_drop_analyze_validate(settings, sb):
    svc = service(settings, sb)
    src = sb / "inbox" / "scan0042.pdf"
    item = svc.drop(src)
    staged = Path(item.staged_path)
    assert not src.exists() and staged.exists()
    assert staged.parent == sb / "root" / "_TriBin" / "a_trier"
    item = svc.analyze(item.file_id)
    assert item.status == "ready" and item.proposal.new_name == "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    prepared = svc.prepare([Validation(item.file_id, item.proposal.target_folder, item.proposal.new_name, "accepted")])
    assert prepared.report.ok and not prepared.needs_confirmation
    result = svc.commit(prepared)
    assert result.done and (sb / "root" / NOEL / "06_Admin" / item.proposal.new_name).exists()
    assert svc.pending() == []


def test_queue_survives_restart(settings, sb):
    svc = service(settings, sb)
    item = svc.drop(sb / "inbox" / "notes.txt")
    svc.analyze(item.file_id)
    again = service(settings, sb)
    pending = again.pending()
    assert [p.file_id for p in pending] == [item.file_id] and pending[0].proposal is not None


def test_interrupted_analysis_is_recovered(settings, sb):
    svc = service(settings, sb)
    item = svc.drop(sb / "inbox" / "notes.txt")
    assert [i.file_id for i in service(settings, sb).recover()] == [item.file_id]


def test_return_to_origin(settings, sb):
    svc = service(settings, sb)
    src = sb / "inbox" / "BC_4512.pdf"
    content = src.read_bytes()
    item = svc.drop(src)
    svc.return_to_origin(item.file_id)
    assert src.read_bytes() == content and not Path(item.staged_path).exists()
    assert svc.pending() == []


def test_refusals(settings, sb):
    svc = service(settings, sb)
    with pytest.raises(BinError, match="dossier"):
        svc.drop(sb / "inbox")
    protected = sb / "root" / NOEL / "03_Execution" / "_PROJET_EN_COURS" / "Noel_mise-en-page.indd"
    with pytest.raises(BinError, match="protégé"):
        svc.drop(protected)
    assert protected.exists()
    item = svc.drop(sb / "inbox" / "notes.txt")
    with pytest.raises(BinError, match="déjà dans la corbeille"):
        svc.drop(Path(item.staged_path))


def test_batch_and_new_folder_need_confirmation(settings, sb):
    svc = service(settings, sb, llm=fixed(target_folder="ACME/2027/2027-001_Nouveau/06_Admin", description="Devis"))
    a, b = svc.drop(sb / "inbox" / "scan0042.pdf"), svc.drop(sb / "inbox" / "BC_4512.pdf")
    a, b = svc.analyze(a.file_id), svc.analyze(b.file_id)
    prepared = svc.prepare([Validation(i.file_id, i.proposal.target_folder, i.proposal.new_name, "accepted") for i in (a, b)])
    assert prepared.needs_confirmation
    assert any(op.action == "mkdir" for op in prepared.batch.ops)
    assert len(svc.commit(prepared).done) >= 2


def test_without_api_key_proposal_is_manual(settings, sb):
    def no_key(settings, model=None):
        raise LLMError("Clé API Anthropic manquante")

    svc = service(settings, sb, factory=no_key)
    item = svc.analyze(svc.drop(sb / "inbox" / "notes.txt").file_id)
    assert item.proposal.manual and "Clé API" in item.proposal.reasoning


def test_locked_file_stays_pending(settings, sb, monkeypatch):
    svc = service(settings, sb)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    prepared = svc.prepare([Validation(item.file_id, item.proposal.target_folder, item.proposal.new_name, "accepted")])

    def locked(a, b):
        raise PermissionError(32, "verrouillé")

    monkeypatch.setattr(restore.os, "rename", locked)
    svc.commit(prepared)
    pending = svc.pending()
    assert pending[0].status == "ready" and "ferme-le" in pending[0].error
    assert Path(item.staged_path).exists()
