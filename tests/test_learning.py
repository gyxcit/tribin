"""Phase 5 : apprentissage à partir des corrections."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeLLM, original_name

from tribin.convention.loader import load_convention
from tribin.db import Database
from tribin.learning.corrections import contradicts_team, list_corrections, name_conforms, similar_examples, team_rule_alerts
from tribin.learning.rules_store import delete_rule, list_rules, update_rule
from tribin.learning.signals import RulesSummary, check_moved_files, maybe_summarize, remember_placement
from tribin.models import LLMProposal
from tribin.service.bin import BinService, Validation
from tribin.service.config_store import AppConfig

NOEL = "ACME/2026/2026-042_Campagne-Noel"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def sb(settings, sandbox_dir: Path) -> Path:
    dest = settings.sandbox_dir / "copy"
    shutil.copytree(sandbox_dir, dest)
    inbox = dest / "inbox"
    for i in range(1, 6):  # devis d'imprimeur supplémentaires, tous semblables
        (inbox / f"devis_imprimeur_{i}.txt").write_text(
            f"DEVIS imprimeur n°{i} pour Acme Corporation, campagne Noël 2026-042, affiches abribus.", encoding="utf-8")
    return dest


def smart_llm() -> FakeLLM:
    """IA simulée qui suit les exemples de corrections présents dans le prompt (comme le demande la consigne)."""

    def answer(prompt: str) -> LLMProposal:
        section = prompt.split("## Corrections passées semblables", 1)
        if len(section) == 2:
            match = re.search(r"→ (\S+)/[^/\s]+ \(l'IA proposait", section[1])
            if match:
                return LLMProposal(target_folder=match.group(1), description="Devis imprimeur", confidence=0.85)
        return LLMProposal(target_folder=f"{NOEL}/06_Admin", description="Devis imprimeur", confidence=0.8)

    return FakeLLM(answer)


def make_service(settings, sb: Path, llm: FakeLLM) -> BinService:
    svc = BinService(settings, provider_factory=lambda s, m=None: llm)
    svc.update_config(AppConfig(roots=[str(sb / "root")], convention_path=str(sb / "convention.yaml"), onboarding_done=True))
    return svc


def place(svc: BinService, sb: Path, name: str, folder: str | None = None, new_name: str | None = None):
    item = svc.analyze(svc.drop(sb / "inbox" / name).file_id)
    p = item.proposal
    folder, final = folder or p.target_folder, new_name or p.new_name
    decision = "accepted" if (folder, final) == (p.target_folder, p.new_name) else "edited"
    svc.commit(svc.prepare([Validation(item.file_id, folder, final, decision)]))
    return item


def test_three_coherent_corrections_change_the_fourth(settings, sb):
    llm = smart_llm()
    svc = make_service(settings, sb, llm)
    first = None
    for i in (1, 2, 3):  # l'utilisateur range les devis d'imprimeur dans 03_Execution plutôt que 06_Admin
        item = place(svc, sb, f"devis_imprimeur_{i}.txt", folder=f"{NOEL}/03_Execution")
        first = first or item
    assert first.proposal.target_folder == f"{NOEL}/06_Admin"
    fourth = svc.analyze(svc.drop(sb / "inbox" / "devis_imprimeur_4.txt").file_id)
    assert fourth.proposal.target_folder == f"{NOEL}/03_Execution"
    assert "Corrections passées semblables" in llm.prompts[-1] and "devis_imprimeur_1.txt" in llm.prompts[-1]
    assert list_corrections(svc.db)[-1].decision == "edited"  # la plus ancienne : la vraie correction


def test_correction_against_team_convention_is_not_learned(settings, sb):
    llm = smart_llm()
    svc = make_service(settings, sb, llm)
    for i in (1, 2, 3):
        place(svc, sb, f"devis_imprimeur_{i}.txt", folder="Divers", new_name=f"devis final {i}.txt")
    corrections = list_corrections(svc.db)
    assert all(c.contradicts_team for c in corrections)
    item = svc.analyze(svc.drop(sb / "inbox" / "devis_imprimeur_4.txt").file_id)
    assert item.proposal.target_folder == f"{NOEL}/06_Admin"  # préférence non apprise
    assert "Corrections passées" not in llm.prompts[-1]
    alerts = team_rule_alerts(svc.db)
    assert any("structure" in a for a in alerts) and any("nommage" in a for a in alerts)


def test_personal_mode_learns_from_folders_outside_the_categories(settings, sb):
    """Mode particulier : pas d'équipe. « startup », dossier créé par l'utilisateur, est un choix comme un autre."""
    from tribin.service.conventions import create_convention

    llm = smart_llm()
    svc = make_service(settings, sb, llm)
    cfg = svc.config
    cfg.convention_path = str(create_convention("personal", cfg.roots, settings.data_dir)[0])
    svc.update_config(cfg)
    (sb / "root" / "startup").mkdir()
    for i in (1, 2):
        place(svc, sb, f"devis_imprimeur_{i}.txt", folder="startup")
    assert not any(c.contradicts_team for c in list_corrections(svc.db))
    svc.analyze(svc.drop(sb / "inbox" / "devis_imprimeur_3.txt").file_id)
    assert "→ startup/" in llm.prompts[-1].split("## Corrections passées semblables")[1]
    assert team_rule_alerts(svc.db) == []

    # corrections enregistrées avant cette version (marquées « contraires à l'équipe ») : utilisées quand même
    with svc.db.tx() as c:
        c.execute("UPDATE corrections SET contradicts_team=1")
    info = svc.queue.active()[-1]
    from tribin.extract import extract

    staged = extract(Path(info.staged_path))
    assert similar_examples(svc.db, staged, None) == []
    assert similar_examples(svc.db, staged, None, personal=True)


def test_name_conformity():
    conv = load_convention(REPO / "convention.example.yaml")
    assert name_conforms("2026-10-12_ACME_2026-042_Devis-Impression_v02.pdf", conv)
    assert name_conforms("2026-10-12_ACME_Devis-Impression.pdf", conv)
    assert name_conforms("2026-10-12_ACME_2026-042_Devis_2.pdf", conv)
    assert not name_conforms("devis final ACME.pdf", conv)
    assert not name_conforms("ACME_2026-10-12_Devis.pdf", conv)
    assert contradicts_team("ACME/2026/2026-042_Campagne-Noel/06_Admin", "2026-10-12_ACME_Devis.pdf", conv) == []
    assert contradicts_team("Divers", "devis.pdf", conv) == ["structure", "nommage"]


def test_rules_summary_every_20_and_editable(settings, sb):
    llm = smart_llm()
    svc = make_service(settings, sb, llm)
    for i in (1, 2, 3):
        place(svc, sb, f"devis_imprimeur_{i}.txt", folder=f"{NOEL}/03_Execution")
    summarizer = FakeLLM(lambda prompt: RulesSummary(rules=["Tu ranges les devis d'imprimeur dans 03_Execution."]))
    assert not maybe_summarize(svc.db, summarizer, every=20)  # 3 corrections : pas encore
    assert maybe_summarize(svc.db, summarizer, every=1)
    assert "l'IA proposait" in summarizer.prompts[0]
    rules = list_rules(svc.db, kind="learned")
    assert [r.text for r in rules] == ["Tu ranges les devis d'imprimeur dans 03_Execution."]
    # deux validations sans modification du même modèle de nom : règle confirmée créée sans ouvrir la page Règles
    assert [r.kind for r in list_rules(svc.db, kind="confirmed")] == ["confirmed"]
    update_rule(svc.db, rules[0].id, "Tu ranges les devis d'imprimeur dans 03_Execution, sauf les signés.")
    svc.analyze(svc.drop(sb / "inbox" / "devis_imprimeur_5.txt").file_id)
    assert "sauf les signés" in llm.systems[-1] and "Règles de cet utilisateur" in llm.systems[-1]
    assert "sauf les signés" not in llm.prompts[-1]  # le contexte stable est dans le system (cache de prompt)
    delete_rule(svc.db, rules[0].id)
    assert list_rules(svc.db, kind="learned") == []


def test_implicit_signal_when_moved_by_hand(settings, sb):
    llm = smart_llm()
    svc = make_service(settings, sb, llm)
    item = place(svc, sb, "devis_imprimeur_1.txt")
    placed = sb / "root" / item.proposal.target_folder / item.proposal.new_name
    assert placed.exists()
    other = sb / "root" / NOEL / "01_Brief" / placed.name
    os.rename(placed, other)  # déplacé à la main
    assert svc.check_implicit_corrections() == 1
    implicit = [c for c in list_corrections(svc.db) if c.source == "implicit"]
    assert implicit and implicit[0].final_folder == f"{NOEL}/01_Brief"
    assert svc.check_implicit_corrections() == 0  # vérifié une seule fois


def test_implicit_signal_expires_after_14_days(settings, sb, tmp_path):
    db = Database(tmp_path / "x.db")
    conv = load_convention(sb / "convention.yaml")
    f = sb / "root" / NOEL / "06_Admin" / "a.txt"
    f.write_text("x")
    remember_placement(db, "op_1", f, sb / "root", f"{NOEL}/06_Admin", "a.txt", "a.txt", "ACME")
    os.rename(f, sb / "root" / NOEL / "01_Brief" / "a.txt")
    assert check_moved_files(db, conv, now=datetime.now() + timedelta(days=15)) == 0


def test_examples_filtered_by_similarity(settings, sb):
    svc = make_service(settings, sb, smart_llm())
    place(svc, sb, "devis_imprimeur_1.txt", folder=f"{NOEL}/03_Execution")
    from tribin.extract import extract

    unrelated = extract(sb / "inbox" / "IMG_3381.jpg")
    assert similar_examples(svc.db, unrelated, "BRIOC") == []
    similar = extract(sb / "inbox" / "devis_imprimeur_2.txt")
    assert len(similar_examples(svc.db, similar, "ACME")) == 1
    assert original_name("Nom d'origine : x.pdf\n") == "x.pdf"


def test_rule_kinds_confirmed_rules_and_text_view(tmp_path):
    from tribin.db import Database
    from tribin.learning.rules_store import (
        add_rule,
        apply_text,
        delete_rule,
        list_rules,
        refresh_confirmed_rules,
        replace_rules,
        rules_as_text,
    )

    db = Database(tmp_path / "t.db")

    def accepted(name, folder):
        with db.tx() as c:
            c.execute("INSERT INTO corrections(ts, original_name, extension, final_folder, final_name, decision, "
                      "changed_fields, contradicts_team, source) VALUES('2026-10-25', ?, '.pdf', ?, ?, 'accepted', "
                      "'[]', 0, 'explicit')", (name, folder, name))

    accepted("2026_07_likassi_regis_2026_07_28T13_45_02.pdf", "salaire")
    assert refresh_confirmed_rules(db) == 0  # une seule validation : pas encore une règle
    accepted("2026_08_likassi_regis_2026_08_29T10_12_44.pdf", "salaire")
    assert refresh_confirmed_rules(db) == 1
    rule = list_rules(db, kind="confirmed")[0]
    assert "salaire" in rule.text and rule.details["count"] == 2 and len(rule.details["examples"]) == 2
    delete_rule(db, rule.id)
    assert refresh_confirmed_rules(db) == 0 and not list_rules(db, kind="confirmed")  # supprimée : jamais recréée

    add_rule(db, "Les factures d'électricité vont dans Logement/Energie.")
    replace_rules(db, ["Les devis signés vont dans Admin."], {"count": 5, "corrections": ["- « a.pdf »"]})
    assert [r.kind for r in list_rules(db)] == ["manual", "learned"]  # la synthèse garde les règles ajoutées
    text = rules_as_text(db)
    assert "[ajoutée] Les factures" in text and "[apprise] Les devis" in text
    apply_text(db, text.replace("[apprise] Les devis", "# [apprise] Les devis") + "\nLes CV vont dans Etudes/CV.")
    rules = {r.text: r for r in list_rules(db)}
    assert not rules["Les devis signés vont dans Admin."].enabled  # « # » : désactivée, logique gardée
    assert rules["Les devis signés vont dans Admin."].details["count"] == 5
    assert rules["Les CV vont dans Etudes/CV."].kind == "manual"
    apply_text(db, "Les CV vont dans Etudes/CV.")
    assert [r.text for r in list_rules(db)] == ["Les CV vont dans Etudes/CV."]  # lignes effacées : supprimées


def test_examples_need_a_similar_name_not_just_the_same_extension(tmp_path):
    """Une correction sur un CV ne sert pas d'exemple pour un relevé bancaire parce que les deux sont des PDF."""
    from tribin.extract import base_info
    from tribin.learning.corrections import record_correction
    from tribin.models import NameFields, Proposal

    db = Database(tmp_path / "x.db")
    conv = load_convention(REPO / "src/tribin/resources/convention.personal.yaml")
    ai = Proposal(file_id="f", target_folder="Administratif", new_name="cv.pdf", fields=NameFields(), confidence=0.9,
                  reasoning="", prompt_version="", model="")
    record_correction(db, conv, "CV Regis 2026.pdf", "", None, ai, "Etudes/CV", "2026-10-19_CV-Regis.pdf", "edited")
    for name in ("Releve_LCL_2026-09.pdf", "IMG_3381.pdf"):
        (tmp_path / name).write_bytes(b"")
        assert similar_examples(db, base_info(tmp_path / name), None, personal=True) == []
    (tmp_path / "cv regis v2.pdf").write_bytes(b"")
    assert len(similar_examples(db, base_info(tmp_path / "cv regis v2.pdf"), None, personal=True)) == 1
    (tmp_path / "Lettre Regis.docx").write_bytes(b"")  # mot distinctif commun, extension différente
    assert len(similar_examples(db, base_info(tmp_path / "Lettre Regis.docx"), None, personal=True)) == 1


def test_rules_summary_prompt_by_mode():
    from tribin.learning.signals import summary_system

    work, personal = summary_system(False), summary_system(True)
    assert "06_Admin" in work and "convention d'équipe" in work
    assert "06_Admin" not in personal and "équipe" not in personal
    for text in (work, personal):
        assert "Jamais de règle sur le format du nom" in text
