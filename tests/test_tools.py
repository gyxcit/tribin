"""Outils appelés par l'IA (skill v2, § 2.4) : registre, budget, `lister_dossiers`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fakes import fixed

from tribin.convention.loader import load_convention
from tribin.engine.proposer import ProposeContext, propose
from tribin.engine.tools import (
    BUDGET_MESSAGE,
    MAX_FOLDERS_PER_ANSWER,
    Tool,
    ToolSession,
    folder_lister,
    looked_at,
)
from tribin.extract import extract
from tribin.mapping.profiles import FolderProfile
from tribin.mapping.scanner import scan_root

NOEL = "ACME/2026/2026-042_Campagne-Noel"


@pytest.fixture
def perso_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    for rel in ("Etudes/CV", "Etudes/Attestations/2025", "Etudes/Certifications", "Photos", "startup", "_TriBin/a_trier",
                "_Archive", ".cache", "Sante"):
        (root / rel).mkdir(parents=True)
    (root / "Etudes/CV/2026-10-19_CV-ingenieur-IA.pdf").write_bytes(b"x")
    (root / "Etudes/CV/2026-10-19_CV-ingenieur-IA_2.pdf").write_bytes(b"x")
    (root / "Etudes/Attestations/2025-02-20_Attestation-mission-benevole.pdf").write_bytes(b"x")
    (root / "startup/Presentation-projet-Stagio_2026-10-20.pdf").write_bytes(b"x")
    (root / "startup/Thumbs.db").write_bytes(b"x")
    return root


def lister(root: Path, excluded=None):
    from tribin.convention.loader import Convention

    return folder_lister(root, scan_root(root, Convention(excluded_paths=excluded or [])), excluded)


def test_root_and_subfolders_from_profiles(perso_root):
    tool = lister(perso_root)
    assert tool.declaration["name"] == "lister_dossiers" and tool.declaration["input_schema"]["required"] == ["chemin"]
    answer = tool.call({"chemin": ""})
    assert answer["chemin"] == "" and answer["fichiers_ici"] == 0 and not answer["tronque"]
    assert [d["nom"] for d in answer["dossiers"]] == ["Etudes", "Photos", "Sante", "startup"]  # ni _TriBin ni .cache
    etudes = next(d for d in answer["dossiers"] if d["nom"] == "Etudes")
    assert etudes == {"nom": "Etudes", "fichiers": 0, "sous_dossiers": 3, "exemples": []}
    startup = next(d for d in answer["dossiers"] if d["nom"] == "startup")
    assert startup["fichiers"] == 1 and startup["exemples"] == ["Presentation-projet-Stagio_2026-10-20.pdf"]

    deep = tool.call({"chemin": "Etudes", "profondeur": 2})
    cv = next(d for d in deep["dossiers"] if d["nom"] == "CV")
    assert cv["fichiers"] == 2 and len(cv["exemples"]) == 2 and cv["dossiers"] == []
    attest = next(d for d in deep["dossiers"] if d["nom"] == "Attestations")
    assert attest["sous_dossiers"] == 1 and [d["nom"] for d in attest["dossiers"]] == ["2025"]
    assert tool.call({"chemin": "etudes/cv"})["chemin"] == "Etudes/CV"  # casse tolérée


def test_refused_and_unknown_paths(perso_root):
    tool = lister(perso_root, excluded=["Photos/**"])
    for bad in ("..", "../autre", "/etc", "C:/Users", "~/Documents", "Etudes/../.."):
        assert "erreur" in tool.call({"chemin": bad}) and "dossiers" not in tool.call({"chemin": bad}), bad
    for internal in ("_TriBin", "_TriBin/a_trier", "_Archive", ".cache", "Photos"):
        assert "erreur" in tool.call({"chemin": internal}), internal
    missing = tool.call({"chemin": "Design"})
    assert missing["erreur"] == "Dossier introuvable : Design" and "lister_dossiers" in missing["suggestion"]


def test_scandir_fallback_for_folders_created_after_the_map(perso_root):
    tool = lister(perso_root)
    (perso_root / "Graphisme" / "Sarah").mkdir(parents=True)
    (perso_root / "Graphisme" / "logo.png").write_bytes(b"x")
    answer = tool.call({"chemin": "Graphisme"})
    assert answer["fichiers_ici"] == 1 and answer["exemples"] == ["logo.png"]
    assert answer["dossiers"] == [{"nom": "Sarah", "fichiers": 0, "sous_dossiers": 0, "exemples": []}]
    empty = folder_lister(perso_root, profiles=None)  # aucun profil : la racine est lue sur le disque
    assert [d["nom"] for d in empty.call({"chemin": ""})["dossiers"]] == ["Etudes", "Graphisme", "Photos", "Sante", "startup"]


def test_truncation():
    profiles = [FolderProfile(rel=f"D{i:03d}", file_count=1, samples=[f"f{i}.pdf"]) for i in range(80)]
    answer = folder_lister(Path("."), profiles).call({"chemin": ""})
    assert len(answer["dossiers"]) == MAX_FOLDERS_PER_ANSWER and answer["tronque"] and "précise" in answer["precision"]
    assert answer["dossiers"][0]["exemples"] == ["f0.pdf"]


def test_budget_and_journal():
    calls = []
    echo = Tool("echo", "répète", {"type": "object", "properties": {}}, lambda args: {"vu": args})
    session = ToolSession([echo], max_calls=3)
    assert session.declarations == [echo.declaration]
    for i in range(3):
        assert json.loads(session("echo", {"n": i})) == {"vu": {"n": i}}
    assert session.exhausted
    assert json.loads(session("echo", {"n": 3})) == {"erreur": BUDGET_MESSAGE}
    assert json.loads(session("echo", {"n": 4})) == {"erreur": BUDGET_MESSAGE}
    assert [c.get("refuse", False) for c in session.calls] == [False, False, False, True, True]
    assert json.loads(ToolSession([echo])("inconnu", {})) == {"erreur": "Outil inconnu : inconnu"}
    boom = Tool("boom", "plante", {}, lambda args: calls.append(1) or 1 / 0)
    assert "a échoué" in json.loads(ToolSession([boom])("boom", None))["erreur"]
    journal = [{"outil": "lister_dossiers", "arguments": {"chemin": ""}}, {"outil": "lister_dossiers", "arguments": {"chemin": "Etudes/"}},
               {"outil": "lister_dossiers", "arguments": {"chemin": ""}}, {"outil": "lister_dossiers", "arguments": {"chemin": "X"}, "refuse": True}]
    assert looked_at(journal) == ["racine", "Etudes"]


def test_propose_passes_the_tools_and_records_the_calls(sandbox_dir: Path, tmp_path: Path):
    sb = tmp_path / "sb"
    shutil.copytree(sandbox_dir, sb)
    llm = fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.9)
    llm.tool_script = [("lister_dossiers", {"chemin": ""}), ("lister_dossiers", {"chemin": "ACME/2026"}),
                       ("lister_dossiers", {"chemin": "Nulle-part"}), ("lister_dossiers", {"chemin": ""})]
    ctx = ProposeContext(root=sb / "root", convention=load_convention(sb / "convention.yaml"), llm=llm)
    p = propose(extract(sb / "inbox" / "scan0042.pdf"), ctx)
    assert [t["name"] for t in llm.tools[0]] == ["lister_dossiers"]
    root_answer = json.loads(llm.tool_results[0])
    assert {"ACME", "BRIOC", "VELOM", "Administratif"} <= {d["nom"] for d in root_answer["dossiers"]}
    assert [d["nom"] for d in json.loads(llm.tool_results[1])["dossiers"]] == ["2026-042_Campagne-Noel"]
    assert "introuvable" in json.loads(llm.tool_results[2])["erreur"]
    assert json.loads(llm.tool_results[3]) == {"erreur": BUDGET_MESSAGE}  # 4e appel : budget épuisé
    assert len(p.tool_calls) == 4 and p.tool_calls[-1]["refuse"] and looked_at(p.tool_calls) == ["racine", "ACME/2026", "Nulle-part"]
    assert "lister_dossiers" in llm.systems[0] and "## Arborescence" not in llm.systems[0]

    legacy = fixed(target_folder=f"{NOEL}/06_Admin", description="Devis", confidence=0.9)
    ctx.llm, ctx.prompt_style = legacy, "p7"
    propose(extract(sb / "inbox" / "scan0042.pdf"), ctx)
    assert legacy.tools[0] is None  # l'ancien prompt ne connaît pas les outils
