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


def test_duplicate_alternatives_dropped_and_real_one_needs_review(sb):
    from tribin.models import LLMAlternative

    same = LLMAlternative(target_folder=f"{NOEL}/06_Admin", description="Devis", reasoning="identique")
    other = LLMAlternative(target_folder=f"{NOEL}/01_Brief", description="Brief", reasoning="autre piste")
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.95, alternatives=[same]))
    assert p.alternatives == [] and p.confidence == 0.95 and not p.needs_review
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.95, alternatives=[same, other]))
    assert [a.target_folder for a in p.alternatives] == [f"{NOEL}/01_Brief"]
    assert p.confidence == 0.74 and p.hesitant and p.needs_review  # une alternative : deux dossiers se défendent
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.6, alternatives=[other]))
    assert p.confidence == 0.6  # en dessous du plafond : inchangée
    assert any("hésite" in w for w in p.warnings)


@pytest.mark.parametrize("folder", ["null/CV/04_Livrables", "None/2026/Projet/01_Brief", "{client}/2026/x/01_Brief",
                                    f"{NOEL.split('/')[0]}/inconnu/06_Admin"])
def test_never_a_folder_named_null(sb, folder):
    from tribin.models import LLMAlternative

    p, _ = run(sb, fixed(target_folder=folder, client="null", project_code="null", description="CV ingénieur IA",
                         confidence=0.45, alternatives=[LLMAlternative(target_folder="null/CV/02_Creation")]))
    assert p.manual and p.target_folder == "" and not p.alternatives
    assert "null" not in p.new_name.lower() and "Changer" in p.reasoning


def test_null_alternative_dropped_but_valid_choice_kept(sb):
    from tribin.models import LLMAlternative

    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", client="ACME", project_code="null", description="Devis",
                         confidence=0.9, alternatives=[LLMAlternative(target_folder="null/CV/06_Admin")]))
    assert p.target_folder == f"{NOEL}/06_Admin" and not p.alternatives and p.confidence == 0.9
    assert "null" not in p.new_name.lower()


def test_ai_never_proposes_the_staging_folder(sb):
    p, _ = run(sb, fixed(target_folder="_TriBin/a_trier", description="CV", confidence=0.9))
    assert p.manual and p.target_folder == ""


def test_files_with_same_name_pattern_point_to_their_folder(sb):
    from tribin.engine.similar import PlacedFiles, name_pattern

    assert name_pattern("2026_03_lefort_marie_2026_03_25T08_57_09.pdf") == name_pattern(
        "2026_08_lefort_marie_2026_08_29T10_12_44.pdf")
    placed = PlacedFiles(sb / "root")
    found = placed.similar("2026_09_lefort_marie_2026_09_29T09_41_07.pdf")
    assert [s.folder for s in found] == ["Administratif/Bulletins-de-paie"] and found[0].count == 1
    assert placed.similar("IMG_3381.jpg") == []  # nom générique : aucun signal

    llm = fixed(target_folder="Administratif/Bulletins-de-paie", description="Bulletin de paie", confidence=0.9)
    ctx = ProposeContext(root=sb / "root", convention=load_convention(sb / "convention.yaml"), llm=llm)
    ctx.similar_provider = lambda info: placed.similar(info.name)
    p = propose(extract(sb / "inbox" / "2026_09_lefort_marie_2026_09_29T09_41_07.pdf"), ctx)
    assert "Fichiers déjà rangés qui ressemblent à celui-ci" in llm.prompts[0]
    candidates = llm.prompts[0].split("## Dossiers candidats")[1].split("##")[0]
    assert "- Administratif/Bulletins-de-paie" in candidates  # toujours proposé parmi les candidats
    assert p.target_folder == "Administratif/Bulletins-de-paie" and not p.folder_is_new and p.confidence == 0.9
    assert "_v" not in p.new_name  # l'heure du nom d'origine n'est pas une version


def test_files_sharing_a_distinctive_word_point_to_their_folder(tmp_path):
    """« Stagio Traitement.html » : « startup » contient déjà « Presentation-projet-Stagio… » (même projet)."""
    from tribin.engine.similar import PlacedFiles

    for rel in ("startup/Presentation-projet-Stagio_2026-10-20.pdf", "Etudes/CV/2026-10-19_CV-projet-IA.pdf",
                "Factures/Facture-projet-loyer.pdf", "Banque/Releve-projet-epargne.pdf"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    found = PlacedFiles(tmp_path).similar("Stagio Traitement.html")
    assert [(s.folder, s.word) for s in found] == [("startup", "stagio")]
    assert "dont le nom contient « stagio »" in found[0].render()
    assert PlacedFiles(tmp_path).similar("Projet final.docx") == []  # « projet » : dans trop de dossiers


# --- skill v2 : date du document, indices, casse, versions ---------------------------------------------


def test_no_date_rather_than_the_file_date(sb):
    """Un document de 2024 téléchargé aujourd'hui : sans date lue, pas de date dans le nom (plutôt rien qu'une fausse)."""
    from tribin.engine.proposer import NO_DATE_WARNING

    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Facture EDF", confidence=0.8,
                         document_date_source="aucune", date=None))
    assert p.new_name == "ACME_2026-042_Facture-EDF.pdf" and NO_DATE_WARNING in p.warnings
    old_style, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Facture EDF", confidence=0.8))
    assert old_style.new_name.startswith("2026-10-13_")  # réponse de l'ancien prompt : date du fichier, comme avant
    assert NO_DATE_WARNING not in old_style.warnings


def test_photos_keep_their_shooting_date(sb):
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/05_Sources", description="Packshot", confidence=0.7,
                         document_date_source="aucune"), "IMG_3381.jpg")
    assert p.new_name.startswith("2026-02-20_") and not any("sans date" in w for w in p.warnings)


def test_analysis_fields_kept_and_shown(sb):
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.9, document_kind="devis",
                         subject="affiches ACME", document_date_source="contenu", date="2026-10-12",
                         evidence=["en-tête DEVIS", " projet 2026-042 ", ""]))
    assert (p.document_kind, p.subject, p.document_date_source) == ("devis", "affiches ACME", "contenu")
    assert p.evidence == ["en-tête DEVIS", "projet 2026-042"]
    assert p.input_tokens == 100 and p.output_tokens == 50  # consommation du faux fournisseur


@pytest.mark.parametrize("value,expected", [
    ("2026-10-12", "2026-10-12"), ("2026-10-12T10:00:00", "2026-10-12"), ("12/10/2026", "2026-10-12"),
    ("12.10.2026", "2026-10-12"), ("2026/10/12", "2026-10-12"), ("20261012", "2026-10-12"), ("2026-10", "2026-10-01"),
    ("10/2026", "2026-10-01"), ("2099-01-01", None), ("1850-03-03", None), ("hier", None), ("", None), (None, None),
])
def test_parse_date_formats_and_bounds(value, expected):
    from datetime import date

    from tribin.engine.proposer import _parse_date

    got = _parse_date(value, today=date(2026, 10, 25))
    assert (got.isoformat() if got else None) == expected


def test_work_mode_canonicalizes_case(sb):
    """« acme/2026/…/06_admin » : la catégorie est reconnue et le dossier existant réutilisé (pas de doublon)."""
    p, _ = run(sb, fixed(target_folder="acme/2026/2026-042_campagne-noel/06_admin", description="Devis", confidence=0.9,
                         date="2026-10-12"))
    assert p.target_folder == f"{NOEL}/06_Admin" and not p.folder_is_new
    assert p.fields.category == "06_Admin" and p.new_name == "2026-10-12_ACME_2026-042_Devis.pdf"
    p2, _ = run(sb, fixed(target_folder="acme/2026/2026-099_nouveau/06_admin", description="Devis", confidence=0.9))
    assert p2.target_folder == "ACME/2026/2026-099_nouveau/06_Admin" and p2.folder_is_new


def test_bare_number_is_a_version_only_in_versioned_categories(sb):
    shutil.copy(sb / "inbox" / "scan0042.pdf", sb / "inbox" / "Facture n 5.pdf")
    shutil.copy(sb / "inbox" / "logo_acme_HD.png", sb / "inbox" / "visuel_3.png")
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Facture", confidence=0.9), "Facture n 5.pdf")
    assert "_v" not in p.new_name
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/02_Creation", description="Visuel", confidence=0.9), "visuel_3.png")
    assert p.new_name.endswith("_v03.png")


def test_alternative_without_description_keeps_the_main_one(sb):
    from tribin.models import LLMAlternative

    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", date="2026-10-12",
                         alternatives=[LLMAlternative(target_folder=f"{NOEL}/01_Brief")]))
    assert p.alternatives[0].new_name == "2026-10-12_ACME_2026-042_Devis.pdf" and "None" not in p.alternatives[0].new_name


# --- mode Particulier : personal_folder / new_category_for -------------------------------------------------


@pytest.fixture
def perso(tmp_path: Path):
    from tribin import resources
    from tribin.convention.loader import load_convention as load

    root = tmp_path / "root"
    for rel in ("Photos/Logos", "Etudes/CV", "startup", "Sante"):
        (root / rel).mkdir(parents=True)
    return root, load(Path(resources.__file__).with_name("convention.personal.yaml"))


def test_existing_target_folder_beats_an_unknown_category(perso):
    from tribin.engine.proposer import new_category_for, personal_folder
    from tribin.models import LLMProposal

    root, conv = perso
    resp = LLMProposal(category="Design", target_folder="Photos/Logos")
    assert new_category_for(resp, conv, "Photos/Logos") is None
    assert personal_folder("Photos/Logos", conv.find_category("Design"), None, conv, root) == "Photos/Logos"


def test_category_with_a_slash_and_missing_category(perso):
    from tribin.engine.proposer import new_category_for, personal_folder
    from tribin.models import LLMProposal

    root, conv = perso
    assert new_category_for(LLMProposal(category="Design/Sarah-Mbossa", target_folder="Design/Sarah-Mbossa"), conv,
                            "Design/Sarah-Mbossa") == "Design"
    assert new_category_for(LLMProposal(category=None, target_folder="Design/Sarah"), conv, "Design/Sarah") == "Design"
    assert personal_folder("Design/Sarah", None, "Design", conv, root) == "Design/Sarah"
    assert new_category_for(LLMProposal(category="null", target_folder=""), conv, "") is None
    assert new_category_for(LLMProposal(category="Santé", target_folder="Sante"), conv, "Sante") is None  # existante


def test_personal_folder_reuses_user_folders_and_depth(perso):
    from tribin.engine.proposer import personal_folder, user_folder

    root, conv = perso
    assert user_folder("Startup/Admin", conv, root) == "startup"
    assert personal_folder("Startup/Admin", None, None, conv, root) == "startup/Admin"
    assert personal_folder("etudes/cv/2026/encore", "Etudes", None, conv, root) == "Etudes/CV/2026"  # 3 niveaux
    assert personal_folder("Banque/null/x", None, None, conv, root) == "Banque"  # segment « null » ignoré
    assert personal_folder("", "Photos", None, conv, root) == "Photos"
    assert personal_folder("", None, None, conv, root) == ""


def test_light_update_refreshes_counts_and_keeps_descriptions(tmp_path):
    from tribin.db import Database
    from tribin.mapping.profiles import FolderProfile, light_update, load_profiles, save_profiles

    db = Database(tmp_path / "t.db")
    save_profiles(db, tmp_path, [FolderProfile(rel="Etudes", file_count=0, description="Diplômes et CV")])
    light_update(db, tmp_path, [FolderProfile(rel="Etudes", file_count=3, samples=["cv.pdf"]), FolderProfile(rel="Sante")])
    by_rel = {p.rel: p for p in load_profiles(db, tmp_path)}
    assert by_rel["Etudes"].file_count == 3 and by_rel["Etudes"].samples == ["cv.pdf"]
    assert by_rel["Etudes"].description == "Diplômes et CV" and "Sante" in by_rel


def test_document_creation_date_used_before_no_date(sb):
    """Sans date lue par l'IA, la date de création écrite dans le document (propriétés Office) sert ; pas celle du fichier."""
    from tribin.engine.proposer import NO_DATE_WARNING

    p, _ = run(sb, fixed(target_folder=f"{NOEL}/01_Brief", description="Brief", confidence=0.8,
                         document_date_source="aucune"), "Document1.docx")
    assert p.new_name.startswith("2026-02-09_") and NO_DATE_WARNING not in p.warnings  # created = 2026-02-09 (métadonnées)
    p, _ = run(sb, fixed(target_folder=f"{NOEL}/06_Admin", description="Notes", confidence=0.8,
                         document_date_source="aucune"), "notes.txt")
    assert not p.new_name[:4].isdigit() and NO_DATE_WARNING in p.warnings  # texte brut : aucune date de document
