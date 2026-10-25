"""Évaluation de la qualité des propositions sur un jeu de test (section 10). Aucun déplacement de fichier."""

from __future__ import annotations

import csv
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean

from tribin.engine.proposer import ProposeContext, propose
from tribin.engine.tools import looked_at
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
    expected_keyword: str = ""  # mot à retrouver dans le nom (nom propre), facultatif
    expected_exists: bool = False  # le dossier attendu existe déjà dans root/ (sinon il est à créer)
    # Codes de la convention : un dossier attendu hors gabarit (« Administratif/Banque ») n'a ni client ni catégorie
    clients: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()

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
        first = self.expected_folder.replace("\\", "/").split("/")[0]
        expected = first if not self.clients or first.casefold() in self.clients else ""
        return bool(self.proposal) and (self.proposal.fields.client or "").casefold() == expected.casefold()

    @property
    def category_ok(self) -> bool:
        last = self.expected_folder.replace("\\", "/").rstrip("/").split("/")[-1]
        expected = last if not self.categories or last.casefold() in self.categories else ""
        return bool(self.proposal) and (self.proposal.fields.category or "").casefold() == expected.casefold()

    @property
    def name_ok(self) -> bool | None:
        if not self.expected_name:
            return None
        return bool(self.proposal) and self.proposal.new_name.casefold() == self.expected_name.casefold()

    @property
    def date_ok(self) -> bool | None:
        """La date du nom proposé est-elle celle du nom attendu (ou absente des deux) ? None sans nom attendu."""
        if not self.expected_name or not self.proposal:
            return None
        return _leading_date(self.proposal.new_name) == _leading_date(self.expected_name)

    @property
    def keyword_ok(self) -> bool | None:
        """Le mot-clé attendu (nom propre : personne, organisme, projet) est-il dans le nom proposé ?"""
        if not self.expected_keyword or not self.proposal:
            return None
        return _fold(self.expected_keyword) in _fold(self.proposal.new_name)


@dataclass
class EvalReport:
    rows: list[EvalRow]
    model: str
    prompt_version: str
    duration_s: float
    metrics: dict[str, float] = field(default_factory=dict)


_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _leading_date(name: str) -> str:
    match = _DATE_PREFIX.match(name)
    return match.group(1) if match else ""


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold().replace("-", " ").replace("_", " ")


def load_expected(testset: Path) -> list[EvalRow]:
    with open(Path(testset) / "expected.csv", encoding="utf-8-sig", newline="") as fh:
        return [
            EvalRow(file=r["file"], expected_folder=r["expected_folder"],
                    acceptable=[f for f in (r.get("acceptable_folders") or "").split("|") if f.strip()],
                    expected_name=(r.get("expected_name") or "").strip(),
                    expected_keyword=(r.get("expected_keyword") or "").strip())
            for r in csv.DictReader(fh)
        ]


def _pct(values: list[bool]) -> float:
    return round(100 * sum(values) / len(values), 1) if values else 0.0


def compute_metrics(rows: list[EvalRow]) -> dict[str, float]:
    done = [r for r in rows if r.proposal]
    named = [r.name_ok for r in rows if r.name_ok is not None]
    good = [r.proposal.confidence for r in done if r.folder_ok]
    bad = [r.proposal.confidence for r in done if not r.folder_ok]
    dated = [r.date_ok for r in rows if r.date_ok is not None]
    keyworded = [r.keyword_ok for r in rows if r.keyword_ok is not None]
    inputs = [r.proposal.input_tokens for r in done if r.proposal.input_tokens]
    cached = sum(r.proposal.cached_input_tokens for r in done)
    calls = [sum(1 for c in r.proposal.tool_calls if not c.get("refuse")) for r in done]
    return {
        "fichiers": len(rows),
        "dossiers_exacts_pct": _pct([r.folder_exact for r in rows]),
        "dossiers_acceptables_pct": _pct([r.folder_ok for r in rows]),
        "clients_corrects_pct": _pct([r.client_ok for r in rows]),
        "categories_correctes_pct": _pct([r.category_ok for r in rows]),
        "noms_exacts_pct": _pct(named) if named else -1,
        "confiance_bonnes": round(mean(good), 2) if good else 0.0,
        "confiance_mauvaises": round(mean(bad), 2) if bad else 0.0,
        # Calibration : une erreur doit être marquée « à vérifier » (confiance < 0,6), une bonne réponse non.
        "erreurs_signalees_pct": _pct([r.proposal.needs_review for r in done if not r.folder_ok]) if bad else -1,
        "bonnes_signalees_pct": _pct([r.proposal.needs_review for r in done if r.folder_ok]) if good else -1,
        # Erreurs présentées avec assurance : le critère de bascule d'un prompt (skill v2, docs/triage-skill-v2.md)
        "erreurs_confiantes": sum(1 for r in done if not r.folder_ok and r.proposal.confidence > 0.8),
        "dates_correctes_pct": _pct(dated) if dated else -1,
        "mots_cles_conserves_pct": _pct(keyworded) if keyworded else -1,
        "sans_date_dans_le_nom": sum(1 for r in done if not _leading_date(r.proposal.new_name)),
        "temps_moyen_s": round(mean(r.proposal.duration_s for r in done), 2) if done else 0.0,
        "cout_moyen_usd": round(mean(r.proposal.cost_usd for r in done), 5) if done else 0.0,
        # Outils (lister_dossiers) : fréquence d'appel et dossiers créés alors que le bon existait déjà
        "appels_outil_par_fichier": round(mean(calls), 2) if calls else 0.0,
        "fichiers_avec_appel_outil_pct": _pct([c > 0 for c in calls]) if calls else 0.0,
        "dossiers_crees_en_double": sum(1 for r in done if r.proposal.folder_is_new and not r.folder_ok and r.expected_exists),
        "jetons_entree_par_fichier": round(mean(inputs)) if inputs else 0,
        "jetons_sortie_par_fichier": round(mean(r.proposal.output_tokens for r in done)) if done else 0,
        "part_lue_depuis_le_cache_pct": round(100 * cached / sum(inputs), 1) if inputs and sum(inputs) else 0.0,
        "a_traiter_manuellement": sum(1 for r in done if r.proposal.manual),
    }


def run_eval(testset: Path, ctx_factory, workers: int = 4) -> EvalReport:
    """Évalue le jeu de test. `ctx_factory(root, convention)` fournit le contexte de proposition."""
    from tribin.convention.loader import load_convention

    testset = Path(testset)
    convention = load_convention(testset / "convention.yaml")
    ctx: ProposeContext = ctx_factory(testset / "root", convention)
    rows = load_expected(testset)
    clients = frozenset(c.code.casefold() for c in convention.clients)
    categories = frozenset(code.casefold() for code in convention.category_codes())
    for row in rows:
        row.clients, row.categories = clients, categories
        row.expected_exists = (testset / "root" / row.expected_folder).is_dir()
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
                         "expected_name", "proposed_name", "confidence", "manual", "reasoning", "error",
                         "needs_review", "document_kind", "date_source", "evidence", "input_tokens", "cached_tokens",
                         "tool_calls"])
        for r in report.rows:
            p = r.proposal
            writer.writerow([r.file, r.expected_folder, p.target_folder if p else "", r.folder_ok, r.client_ok,
                             r.category_ok, r.expected_name, p.new_name if p else "", p.confidence if p else "",
                             p.manual if p else "", p.reasoning if p else "", r.error,
                             p.needs_review if p else "", p.document_kind if p else "",
                             p.document_date_source if p else "", " | ".join(p.evidence) if p else "",
                             p.input_tokens if p else "", p.cached_input_tokens if p else "",
                             ", ".join(looked_at(p.tool_calls)) if p else ""])
        writer.writerow([])
        for key, value in report.metrics.items():
            writer.writerow([key, value])
    return path
