from __future__ import annotations

import shutil
from pathlib import Path

from fakes import oracle

from tribin.engine.prompts import PROMPT_VERSION
from tribin.engine.proposer import ProposeContext
from tribin.eval.evaluate import run_eval, save_report


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*")}


def test_eval_with_oracle_scores_100_and_writes_nothing(sandbox_dir: Path, tmp_path: Path):
    sb = tmp_path / "sb"
    shutil.copytree(sandbox_dir, sb)
    before = _snapshot(sb)
    llm = oracle(sb)
    report = run_eval(sb, lambda root, conv: ProposeContext(root=root, convention=conv, llm=llm))
    assert _snapshot(sb) == before  # phase 1 : aucune écriture
    m = report.metrics
    assert m["fichiers"] == 42
    assert m["dossiers_exacts_pct"] == 100.0
    assert m["clients_corrects_pct"] == 100.0
    assert m["categories_correctes_pct"] == 100.0
    out = save_report(report, tmp_path / "eval_results")
    assert out.exists() and f"fake-model_{PROMPT_VERSION}" in out.name


def test_personal_testset_with_oracle(tmp_path: Path):
    """Jeu Particulier : avec une IA parfaite, 100 % de dossiers exacts, y compris le dossier « Design/… » à créer."""
    from make_sandbox_perso import make_sandbox_perso

    sb = tmp_path / "perso"
    make_sandbox_perso(sb)
    before = _snapshot(sb)
    llm = oracle(sb)
    report = run_eval(sb, lambda root, conv: ProposeContext(root=root, convention=conv, llm=llm))
    assert _snapshot(sb) == before
    m = report.metrics
    assert m["fichiers"] == 27 and m["dossiers_exacts_pct"] == 100.0 and m["a_traiter_manuellement"] == 0
    assert report.prompt_version == "p9-perso" and m["erreurs_confiantes"] == 0
    rows = {r.file: r for r in report.rows}
    logo = rows["Planche de logos Sarah Mbossa-1.png"].proposal
    assert logo.folder_is_new and logo.new_category is None and logo.target_folder == "Graphisme/Sarah-Mbossa"
    assert m["jetons_entree_par_fichier"] == 100 and m["part_lue_depuis_le_cache_pct"] == 0.0
    assert m["appels_outil_par_fichier"] == 0.0 and m["dossiers_crees_en_double"] == 0
