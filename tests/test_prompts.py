"""Skill de triage v2 (p8 / p9-perso) : deux prompts complets, contexte stable dans le system, message par fichier."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fakes import fixed

from tribin import resources
from tribin.convention.loader import load_convention
from tribin.engine import prompts, prompts_legacy
from tribin.engine.prompts import PromptData, build_prompts, build_system_prompt, build_user_prompt, prompt_version
from tribin.engine.proposer import ProposeContext, propose
from tribin.extract import extract

PERSONAL = Path(resources.__file__).with_name("convention.personal.yaml")
NOEL = "ACME/2026/2026-042_Campagne-Noel"

# Tournures de la convention d'équipe qui n'ont rien à faire dans les consignes d'un particulier
AGENCY_PHRASES = ("Convention d'équipe", "Mode Professionnel", "Projets existants", "gabarit de structure",
                  "code de la liste des clients", "convention d'équipe", "Format des projets", "Clients (code")


@pytest.fixture
def sb(sandbox_dir: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "sb"
    shutil.copytree(sandbox_dir, dest)
    return dest


def test_versions_and_styles():
    assert prompt_version(False) == "p8" and prompt_version(True) == "p9-perso"
    assert prompt_version(False, "p7") == "p7" and prompt_version(True, "p7") == "p8-perso"
    assert prompts_legacy.PROMPT_VERSION == "p7"


def test_personal_prompt_has_no_agency_rules():
    system = build_system_prompt(PromptData(personal=True, structure_template="{category}",
                                            categories_with_descriptions="Sante (ordonnances)", naming_template="{date}_{description}"))
    for phrase in AGENCY_PHRASES:
        assert phrase not in system, phrase
    assert "# Mode Particulier" in system and "Convention de rangement" in system and "Mode : Particulier" in system
    assert "client, project_code et project_name = null" in system
    assert "# Exemples" in system and "# Barème de confiance" in system
    assert "appelle l'outil lister_dossiers" in system and "TOUJOURS avant de proposer" in system
    assert "aucun dossier Design ni\nGraphisme" in system  # exemple C : l'outil a été appelé avant de créer
    # Le format de réponse place l'analyse avant la décision
    assert system.index('"document_kind"') < system.index('"target_folder"')
    work = build_system_prompt(PromptData(personal=False, clients_list="ACME : Acme"))
    assert "# Mode Professionnel" in work and "# Mode Particulier" not in work and "Convention d'équipe" in work


def test_creation_rule_follows_the_permission():
    allowed = build_system_prompt(PromptData(personal=True, create_folders=True, depth=3))
    forbidden = build_system_prompt(PromptData(personal=True, create_folders=False, depth=3))
    assert "crée le bon dossier" in allowed and "Ne crée aucun dossier" not in allowed
    assert "Ne crée aucun dossier" in forbidden and "crée le bon dossier" not in forbidden
    assert "AU PLUS 2\n  niveau(x) de sous-dossiers (3 niveaux au total)" in allowed
    assert "Ne propose un nouveau dossier que s'il suit le gabarit" in build_system_prompt(PromptData(personal=False))
    assert "Ne propose aucun nouveau dossier" in build_system_prompt(PromptData(personal=False, create_folders=False))


def test_user_message_contains_only_what_changes_per_file():
    d = PromptData(personal=False, profile="Chef de projet", learned_rules=["Tu ranges X dans Y"], tree=["ACME — 3 — 2026"],
                   original_name="scan0042.pdf", extension=".pdf", mime="application/pdf", size_human="38.0 Ko",
                   created="2026-10-25", modified="2026-10-25", origin_folder="C:/Téléchargements",
                   extracted_text="DEVIS", metadata="pages=1", candidate_folders=[f"{NOEL}/06_Admin — devis"],
                   project_folders=[NOEL], similar_files=["salaire — 2 fichiers au nom du même modèle"],
                   dropped_together=["« a.pdf » → X"], correction_examples=["« b.pdf » → Y/b.pdf (l'IA proposait Z/b.pdf)"],
                   client_hint="ACME (Acme Corporation)", has_image=True)
    user = build_user_prompt(d)
    for absent in ("Chef de projet", "Tu ranges X dans Y", "ACME — 3", "Format de réponse", "Profil", "Convention"):
        assert absent not in user, absent
    for present in ("## Dossiers candidats (chemin — description)", "## Projets existants", "## Fichiers déjà rangés",
                    "## Déposés en même temps", "## Corrections passées semblables", "## Indice", "## Fichier à ranger",
                    "Dates du fichier (pas du document) : créé le 2026-10-25", "Dossier d'origine : C:/Téléchargements",
                    "Métadonnées : pages=1", "Contenu extrait (5 caractères)", "Une image du fichier est jointe."):
        assert present in user, present
    system = build_system_prompt(d)
    for present in ("Chef de projet", "Tu ranges X dans Y", "ACME — 3 — 2026", "## Arborescence"):
        assert present in system, present
    personal = build_user_prompt(PromptData(personal=True, project_folders=[NOEL], client_hint="ACME"))
    assert "Projets existants" not in personal and "Indice" not in personal


def test_truncated_text_and_extraction_error_are_said():
    d = PromptData(extracted_text="x" * 4000, text_truncated=True, extraction_error="Contenu illisible (OSError) : métadonnées seules.")
    user = build_user_prompt(d)
    assert "Contenu extrait (début, 4000 caractères)" in user and "Lecture du contenu : Contenu illisible" in user


def test_system_prefix_is_identical_from_one_file_to_the_next(sb):
    """Cache de prompt : le system (consignes + contexte) ne change pas avec le fichier ; seul le message change."""
    llm = fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.9)
    ctx = ProposeContext(root=sb / "root", convention=load_convention(sb / "convention.yaml"), llm=llm,
                         profile="Agence de pub", learned_rules=["Tu ranges les devis dans 06_Admin"],
                         tree=["ACME — 14 — 2025, 2026"])
    ctx.client_detector = lambda info: "ACME" if "ACME" in info.text else None
    for name in ("scan0042.pdf", "IMG_3381.jpg", "notes.txt"):
        propose(extract(sb / "inbox" / name), ctx)
    assert llm.systems[0] == llm.systems[1] == llm.systems[2]
    assert len({*llm.prompts}) == 3
    assert "Agence de pub" in llm.systems[0] and "## Arborescence" in llm.systems[0]
    from datetime import date

    assert date.today().isoformat() not in llm.systems[0]  # pas de date du jour dans le préfixe (cache)


def test_legacy_p7_prompt_still_available(sb):
    llm = fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.9)
    ctx = ProposeContext(root=sb / "root", convention=load_convention(sb / "convention.yaml"), llm=llm, prompt_style="p7",
                         profile="Agence de pub")
    p = propose(extract(sb / "inbox" / "scan0042.pdf"), ctx)
    assert p.prompt_version == "p7"
    assert llm.systems[0].startswith("Tu es l'assistant de rangement de fichiers d'une équipe")
    assert "## Convention d'équipe" in llm.prompts[0] and "Agence de pub" in llm.prompts[0]
    assert "## Format de réponse attendu" in llm.prompts[0]
    system, user = build_prompts(PromptData(personal=True), "p7")
    assert "Mode personnel" in system and "Mode : personnel" in user


def test_examples_are_in_both_modes():
    for personal in (True, False):
        system = prompts.skill_text(personal)
        assert "Exemple A" in system and "Exemple B" in system and "Exemple C" in system
        assert "Planche de logos Sarah Mbossa" in system
