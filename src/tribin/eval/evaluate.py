"""Évaluation de la qualité des propositions sur un jeu de test (section 10). Aucun déplacement de fichier."""

from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean

from tribin.engine.proposer import ProposeContext, propose
from tribin.extract import extract
from tribin.models import Proposal


@dataclass
class EvalRow:
    file: str
    expected_folder: str
    acceptable: list[str]
    expected_name: str
    proposal: Proposal | None = None
    error: str = ""

    @staticmethod
    def _norm(folder: str) -> str:
        return folder.replace("\\", "/").strip("/").casefold()

    @property
    def folder_exact(self) -> bool:
        return bool(self.proposal) and self._norm(self.proposal.target_folder) == self._norm(self.expected_folder)

    @property
    def folder_ok(self) -> bool:
        if not self.proposal:
            return False
        got = self._norm(self.proposal.target_folder)
        return got in {self._norm(f) for f in [self.expected_folder, *self.acceptable]}

    @property
    def client_ok(self) -> bool:
        expected = self.expected_folder.replace("\\", "/").split("/")[0]
        return bool(self.proposal) and (self.proposal.fields.client or "").casefold() == expected.casefold()

    @property
    def category_ok(self) -> bool:
        expected = self.expected_folder.replace("\\", "/").rstrip("/").split("/")[-1]
        return bool(self.proposal) and (self.proposal.fields.category or "").casefold() == expected.casefold()

    @property
    def name_ok(self) -> bool | None:
        if not self.expected_name:
            return None
        return bool(self.proposal) and self.proposal.new_name.casefold() == self.expected_name.casefold()


@dataclass
class EvalReport:
    rows: list[EvalRow]
    model: str
    prompt_version: str
    duration_s: float
    metrics: dict[str, float] = field(default_factory=dict)


def load_expected(testset: Path) -> list[EvalRow]:
    with open(Path(testset) / "expected.csv", encoding="utf-8-sig", newline="") as fh:
        return [
            EvalRow(file=r["file"], expected_folder=r["expected_folder"],
                    acceptable=[f for f in (r.get("acceptable_folders") or "").split("|") if f.strip()],
                    expected_name=(r.get("expected_name") or "").strip())
            for r in csv.DictReader(fh)
        ]


def _pct(values: list[bool]) -> float:
    return round(100 * sum(values) / len(values), 1) if values else 0.0


def compute_metrics(rows: list[EvalRow]) -> dict[str, float]:
    done = [r for r in rows if r.proposal]
    named = [r.name_ok for r in rows if r.name_ok is not None]
    good = [r.proposal.confidence for r in done if r.folder_ok]
    bad = [r.proposal.confidence for r in done if not r.folder_ok]
    return {
        "fichiers": len(rows),
        "dossiers_exacts_pct": _pct([r.folder_exact for r in rows]),
        "dossiers_acceptables_pct": _pct([r.folder_ok for r in rows]),
        "clients_corrects_pct": _pct([r.client_ok for r in rows]),
        "categories_correctes_pct": _pct([r.category_ok for r in rows]),
        "noms_exacts_pct": _pct(named) if named else -1,
        "confiance_bonnes": round(mean(good), 2) if good else 0.0,
        "confiance_mauvaises": round(mean(bad), 2) if bad else 0.0,
        "temps_moyen_s": round(mean(r.proposal.duration_s for r in done), 2) if done else 0.0,
        "cout_moyen_usd": round(mean(r.proposal.cost_usd for r in done), 5) if done else 0.0,
        "a_traiter_manuellement": sum(1 for r in done if r.proposal.manual),
    }


def run_eval(testset: Path, ctx_factory, workers: int = 4) -> EvalReport:
    """Évalue le jeu de test. `ctx_factory(root, convention)` fournit le contexte de proposition."""
    from tribin.convention.loader import load_convention

    testset = Path(testset)
    convention = load_convention(testset / "convention.yaml")
    ctx: ProposeContext = ctx_factory(testset / "root", convention)
    rows = load_expected(testset)
    started = time.monotonic()

    def work(row: EvalRow) -> None:
        try:
            row.proposal = propose(extract(testset / "inbox" / row.file), ctx)
        except Exception as exc:
            row.error = f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, rows))
    report = EvalReport(rows=rows, model=ctx.llm.model, prompt_version=rows[0].proposal.prompt_version
                        if rows and rows[0].proposal else "", duration_s=round(time.monotonic() - started, 1))
    report.metrics = compute_metrics(rows)
    return report


def save_report(report: EvalReport, out_dir: Path) -> Path:
    """Enregistre eval_results/AAAA-MM-JJ_HHMM_<modèle>_<prompt_version>.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = out_dir / f"{stamp}_{report.model}_{report.prompt_version}.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "expected_folder", "proposed_folder", "folder_ok", "client_ok", "category_ok",
                         "expected_name", "proposed_name", "confidence", "manual", "reasoning", "error"])
        for r in report.rows:
            p = r.proposal
            writer.writerow([r.file, r.expected_folder, p.target_folder if p else "", r.folder_ok, r.client_ok,
                             r.category_ok, r.expected_name, p.new_name if p else "", p.confidence if p else "",
                             p.manual if p else "", p.reasoning if p else "", r.error])
        writer.writerow([])
        for key, value in report.metrics.items():
            writer.writerow([key, value])
    return path
