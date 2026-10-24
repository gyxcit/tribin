from __future__ import annotations

import shutil
from pathlib import Path

from fakes import oracle

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
    assert m["fichiers"] == 40
    assert m["dossiers_exacts_pct"] == 100.0
    assert m["clients_corrects_pct"] == 100.0
    assert m["categories_correctes_pct"] == 100.0
    out = save_report(report, tmp_path / "eval_results")
    assert out.exists() and "fake-model_p1" in out.name
