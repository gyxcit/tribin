from __future__ import annotations

import os
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


def test_auto_file_ranges_only_sure_proposals(settings, sb):
    svc = service(settings, sb)  # confiance 0,9
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    report = svc.auto_file()
    assert [i.file_id for i in report.done] == [item.file_id] and not report.left
    assert (sb / "root" / NOEL / "06_Admin" / item.proposal.new_name).exists() and svc.pending() == []
    journal = svc.executor().journal
    assert any(s.get("decision") == "auto" for s in journal.states().values())
    assert journal.acceptance_rate() is None  # non relu : ne compte pas comme « accepté »


def test_auto_file_leaves_doubtful_files(settings, sb):
    svc = service(settings, sb, llm=fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.7))
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    report = svc.auto_file()
    assert not report.done and report.left[0][1] == "confiance trop faible"
    assert [i.file_id for i in svc.pending()] == [item.file_id]
    assert [i.file_id for i in svc.auto_file(min_confidence=0.6).done] == [item.file_id]  # bouton « prêts »


def test_auto_file_never_creates_folders(settings, sb):
    svc = service(settings, sb, llm=fixed(target_folder="ACME/2027/2027-001_Nouveau/06_Admin", description="Devis",
                                          confidence=0.95))
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    report = svc.auto_file()
    assert not report.done and report.left[0][1] == "un nouveau dossier serait créé"
    assert [i.file_id for i in svc.pending()] == [item.file_id]
    assert not (sb / "root" / "ACME" / "2027").exists()


def test_files_without_ai_are_reanalyzed_after_adding_a_key(settings, sb):
    state = {"key": None}
    good = fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.9)

    def factory(settings, model=None):
        if not state["key"]:
            raise LLMError("Clé API manquante")
        return good

    svc = service(settings, sb, factory=factory)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    assert item.proposal.manual
    state["key"] = "nouvelle-cle"
    svc.update_config(svc.config)  # enregistrement des réglages : les contextes d'IA sont recréés
    assert svc.retry_without_ai() == [item.file_id] and svc.queue.get(item.file_id).status == "analyzing"
    item = svc.analyze(item.file_id)
    assert not item.proposal.manual and item.proposal.target_folder == f"{NOEL}/06_Admin"
    assert svc.retry_without_ai() == []


def test_file_removed_from_staging_leaves_the_queue(settings, sb):
    svc = service(settings, sb)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    Path(item.staged_path).unlink()  # supprimé à la main dans _TriBin/a_trier
    assert svc.retry_without_ai() == [] and svc.pending() == []
    other = svc.drop(sb / "inbox" / "notes.txt")
    Path(other.staged_path).unlink()
    assert svc.analyze(other.file_id).status == "gone" and svc.pending() == []


def test_set_aside_and_resume(settings, sb):
    svc = service(settings, sb)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    svc.set_aside(item.file_id)
    assert svc.pending() == [] and [i.file_id for i in svc.set_aside_items()] == [item.file_id]
    assert Path(item.staged_path).exists()  # rien n'a bougé
    assert not svc.auto_file().done  # jamais rangé automatiquement
    assert svc.resume(item.file_id) == "ready"
    assert [i.file_id for i in svc.pending()] == [item.file_id] and svc.set_aside_items() == []


def test_internal_staging_folder_is_never_a_destination(settings, sb):
    svc = service(settings, sb)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    with pytest.raises(BinError, match="dossier interne"):
        svc.prepare([Validation(item.file_id, "_TriBin", item.proposal.new_name, "edited")])
    svc.save_edits({item.file_id: {"name": "a.pdf", "folder": f"{NOEL}/01_Brief"}})
    assert service(settings, sb).load_edits()[item.file_id]["folder"] == f"{NOEL}/01_Brief"  # après redémarrage


def test_folder_map_follows_new_folders(settings, sb):
    svc = service(settings, sb)
    first = svc.context(sb / "root")
    assert svc.context(sb / "root") is first  # rien n'a changé : même contexte
    (sb / "root" / "salaire").mkdir()
    (sb / "root" / "salaire" / "2026_07_dupont_luc_2026_07_28T13_45_02.pdf").write_bytes(b"%PDF-1.4")
    os.utime(sb / "root" / "salaire", (1_700_000_000, 1_700_000_000))  # Windows met parfois cette date à jour en différé
    second = svc.context(sb / "root")
    assert second is not first
    assert [s.folder for s in second.similar_provider(type("I", (), {"name": "2026_09_dupont_luc_2026_09_01T08_00_00.pdf"})())] == ["salaire"]
    svc.drop(sb / "inbox" / "notes.txt")  # un dépôt dans _TriBin ne reconstruit pas la carte
    assert svc.context(sb / "root") is second


def personal_service(settings, sb, llm):
    from tribin.service.conventions import create_convention

    path, _ = create_convention("personal", [str(sb / "root")], settings.data_dir)
    svc = BinService(settings, provider_factory=lambda s, m=None: llm)
    svc.update_config(AppConfig(roots=[str(sb / "root")], convention_path=str(path), onboarding_done=True,
                                privacy_accepted=True, auto_file=True))
    return svc, path


def test_personal_mode_creates_missing_category(settings, sb):
    from tribin.convention.loader import load_convention

    llm = fixed(category="Animaux", target_folder="null", date="2026-10-12", description="Vaccin chat",
                confidence=0.9)
    svc, path = personal_service(settings, sb, llm)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    p = item.proposal
    assert p.new_category == "Animaux" and p.target_folder == "Animaux" and p.folder_is_new
    assert p.new_name == "2026-10-12_Vaccin-chat.pdf" and p.confidence == 0.9
    assert any("Nouvelle catégorie « Animaux »" in w for w in p.warnings)
    report = svc.auto_file()  # création du dossier de la nouvelle catégorie : sans demander (mode personnel)
    assert [i.file_id for i in report.done] == [item.file_id]
    assert (sb / "root" / "Animaux" / "2026-10-12_Vaccin-chat.pdf").exists()
    assert "Animaux" in load_convention(path).category_codes()  # ajoutée à la liste
    assert "Mode : personnel" in llm.prompts[0] and "Clients" not in llm.prompts[0]


def test_personal_mode_accepts_existing_folder_outside_categories(settings, sb):
    """Cas « Stagio » : l'IA choisit « startup », dossier créé par l'utilisateur, hors de la liste des catégories."""
    from tribin.convention.loader import load_convention

    llm = fixed(category=None, target_folder="Startup", date="2026-10-12", description="Admin Stagio", confidence=0.85)
    svc, path = personal_service(settings, sb, llm)
    (sb / "root" / "startup").mkdir()  # créé après la convention : pas dans la liste des catégories
    (sb / "root" / "startup" / "Presentation-projet-Stagio_2026-10-20.pdf").write_bytes(b"%PDF-1.4")
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    p = item.proposal
    assert not p.manual and p.target_folder == "startup" and not p.folder_is_new  # nom exact du dossier existant
    assert p.new_category is None and "startup" not in [c.lower() for c in load_convention(path).category_codes()]
    assert p.confidence == 0.85 and not any("gabarit" in w for w in p.warnings)

    llm = fixed(category="Startup", target_folder="startup/Admin", description="Admin Stagio", confidence=0.85)
    svc._provider_factory = lambda s, m=None: llm  # catégorie « Startup » inventée : le dossier existant prime
    svc.update_config(svc.config)
    p = svc.analyze(svc.drop(sb / "inbox" / "BC_4512.pdf").file_id).proposal
    assert p.target_folder == "startup/Admin" and p.new_category is None
    assert not any("gabarit" in w for w in p.warnings)


def test_personal_mode_uses_existing_category_and_work_mode_never_invents(settings, sb):
    llm = fixed(category="Santé", target_folder="Sante/2026", date="2026-10-12", description="Ordonnance",
                confidence=0.9)
    svc, _ = personal_service(settings, sb, llm)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    assert item.proposal.new_category is None and item.proposal.target_folder == "Sante/2026"
    # catégorie existante, dossier de l'année à créer : conforme au gabarit -> rangé sans demander
    assert [i.file_id for i in svc.auto_file().done] == [item.file_id]
    assert (sb / "root" / "Sante" / "2026").is_dir()

    work = service(settings, sb, llm=fixed(category="Animaux", target_folder="ACME/2027/X/Animaux", confidence=0.9))
    other = work.analyze(work.drop(sb / "inbox" / "BC_4512.pdf").file_id)
    assert other.proposal.new_category is None  # mode travail : jamais de catégorie inventée


def test_activity_statistics():
    from datetime import date, datetime

    from tribin.service.activity import Placement, compute_stats

    def item(decision, status="done", when=datetime(2026, 10, 3)):
        return Placement("o", "b", when, "f.pdf", "f.pdf", Path("r/A/2026/f.pdf"), None, "A/2026", "A", 0.9,
                         decision, status)

    stats = compute_stats([item("accepted"), item("auto"), item("edited"), item("alternative_chosen"),
                           item("accepted", "undone"), item("reorganisation"),
                           item("accepted", when=datetime(2026, 9, 1))], today=date(2026, 10, 25))
    assert (stats.filed, stats.this_month, stats.accepted, stats.auto, stats.corrected, stats.undone) == (5, 4, 2, 1, 2, 1)
    assert stats.without_correction == 3 / 5


def test_personal_mode_subfolders_up_to_max_depth(settings, sb):
    from tribin.convention.loader import load_convention

    root = sb / "root"
    (root / "Etudes" / "Certifications").mkdir(parents=True)
    # l'IA propose 4 niveaux, avec une casse différente pour le dossier existant : 3 niveaux, nom existant gardé
    llm = fixed(category="Etudes", target_folder="etudes/certifications/Université/Licence", date="2026-06-30",
                description="Diplome licence", confidence=0.9)
    svc, path = personal_service(settings, sb, llm)
    assert load_convention(path).structure.max_depth == 3
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    assert item.proposal.target_folder == "Etudes/Certifications/Universite"
    assert item.proposal.confidence == 0.9 and not any("gabarit" in w for w in item.proposal.warnings)
    assert [i.file_id for i in svc.auto_file().done] == [item.file_id]  # sous-dossier créé sans demander
    assert (root / "Etudes" / "Certifications" / "Universite" / "2026-06-30_Diplome-licence.pdf").exists()

    llm2 = fixed(category="Etudes", target_folder="Etudes", description="CV", confidence=0.9)
    svc2, _ = personal_service(settings, sb, llm2)
    other = svc2.analyze(svc2.drop(sb / "inbox" / "BC_4512.pdf").file_id)
    assert other.proposal.target_folder == "Etudes"  # directement dans la catégorie


def test_old_personal_conventions_switch_to_depth():
    from tribin.convention.loader import Convention

    old = Convention.model_validate({"mode": "personal", "structure": {"template": "{category}/{year}"}})
    assert old.structure.max_depth == 3 and old.structure.template == "{category}"
    work = Convention.model_validate({"structure": {"template": "{client}/{year}/{project}/{category}"}})
    assert work.structure.max_depth == 0  # mode travail : inchangé


def test_date_position_template():
    from tribin.convention.loader import Convention
    from tribin.service.conventions import date_position, date_position_template

    assert date_position_template("{date}_{description}", "_", "none") == "{description}"
    assert date_position_template("{description}", "_", "start") == "{date}_{description}"
    assert date_position_template("{date}_{description}", "_", "end") == "{description}_{date}"
    assert date_position_template("{description}_{date}", "_", "start") == "{date}_{description}"
    work = "{date}_{client}_{project_code}_{description}_v{version}"
    assert date_position_template(work, "_", "none") == "{client}_{project_code}_{description}_v{version}"
    assert date_position_template(work, "_", "start") == work
    for template, position in (("{date}_{description}", "start"), ("{description}_{date}", "end"),
                               ("{description}", "none")):
        assert date_position(Convention.model_validate({"naming": {"template": template}})) == position


def test_local_account(settings):
    from tribin.db import Database
    from tribin.service.account import default_name, get_account, save_account

    db = Database(settings.db_path)
    account = get_account(db, "regis")
    assert account.display_name == "Regis" and account.kind == "local" and account.status == "Compte local"
    assert get_account(db).created_at == account.created_at  # une seule ligne, créée une fois
    saved = save_account(db, "Regis Likassi", "regis@exemple.fr")
    assert saved.initials == "RL" and get_account(db).email == "regis@exemple.fr"
    assert default_name("DOMAINE" + chr(92) + "jean.dupont") == "Jean Dupont"


def test_folder_creation_permission(settings, sb):
    """Réglages › Autorisations : par défaut oui en Particulier, non en Professionnel ; réglable."""
    llm = fixed(category="Design", target_folder="Design/Sarah-Mbossa", description="Logos Sarah Mbossa",
                confidence=0.9)
    svc, _ = personal_service(settings, sb, llm)
    assert svc.creates_folders() and AppConfig().creates_folders("work") is False
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    assert "CRÉE un dossier dédié" in llm.systems[-1]
    prepared = svc.prepare([Validation(item.file_id, item.proposal.target_folder, item.proposal.new_name, "accepted")])
    assert not prepared.needs_confirmation  # autorisé : créés sans demander (annulables)

    cfg = svc.config
    cfg.auto_create_folders = False
    svc.update_config(cfg)
    assert not svc.creates_folders()
    other = svc.analyze(svc.drop(sb / "inbox" / "BC_4512.pdf").file_id)
    assert "Ne crée AUCUN dossier" in llm.systems[-1]
    assert any("avec votre accord" in w for w in other.proposal.warnings)
    prepared = svc.prepare([Validation(other.file_id, other.proposal.target_folder, other.proposal.new_name,
                                       "accepted")])
    assert prepared.needs_confirmation  # sans autorisation : la simulation est montrée avant de créer
    assert other.file_id not in [i.file_id for i in svc.auto_file().done]


def test_files_dropped_together_see_each_other(settings, sb):
    """Une série (« … Sarah Mbossa-1 », « … Sarah Mbossa-2 ») : le second voit où l'IA a mis le premier."""
    for n in (1, 2):
        shutil.copy(sb / "inbox" / "scan0042.pdf", sb / "inbox" / f"Planche logos Sarah Mbossa-{n}.pdf")
    llm = fixed(category="Design", target_folder="Design/Sarah-Mbossa", description="Logos Sarah Mbossa",
                confidence=0.9)
    svc, _ = personal_service(settings, sb, llm)
    first = svc.drop(sb / "inbox" / "Planche logos Sarah Mbossa-1.pdf")
    second = svc.drop(sb / "inbox" / "Planche logos Sarah Mbossa-2.pdf")
    svc.analyze(first.file_id)
    svc.analyze(second.file_id)
    together = llm.prompts[-1].split("## Déposés en même temps")[1].split("##")[0]
    assert "« Planche logos Sarah Mbossa-1.pdf » → Design/Sarah-Mbossa" in together


def test_a_file_already_filed_is_not_filed_twice(settings, sb):
    svc = service(settings, sb)
    item = svc.analyze(svc.drop(sb / "inbox" / "scan0042.pdf").file_id)
    v = Validation(item.file_id, item.proposal.target_folder, item.proposal.new_name, "accepted")
    svc.commit(svc.prepare([v]))
    with pytest.raises(BinError, match="vient déjà d'être rangé"):
        svc.prepare([v])  # second appui sur Entrée pendant / après le rangement
