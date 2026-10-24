"""Service « corbeille » : dépôt, analyse, validation, renvoi à l'origine. Indépendant de l'interface (testable)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from tribin.config import STAGING_DIRNAME, Settings, is_within
from tribin.convention.loader import Convention, ConventionError, load_convention
from tribin.db import Database
from tribin.engine.context import make_context
from tribin.engine.proposer import ProposeContext, propose
from tribin.extract import extract
from tribin.fs.filters import ExclusionMatcher, NotProcessable, check_processable
from tribin.ids import new_id
from tribin.llm import make_provider
from tribin.learning.corrections import record_correction
from tribin.learning.signals import check_moved_files, maybe_summarize, remember_placement
from tribin.llm.base import LLMError, Usage
from tribin.safety import restore
from tribin.safety.executor import ExecutionReport, Executor, SimulationReport
from tribin.safety.operations import Batch, Choice
from tribin.service.config_store import AppConfig, load_config, save_config
from tribin.service.queue import QueueItem, QueueStore

log = logging.getLogger(__name__)


class BinError(Exception):
    """Erreur expliquée à l'utilisateur (en français)."""


class _NoLLM:
    """Fournisseur de remplacement quand l'IA n'est pas configurée : chaque proposition devient manuelle."""

    def __init__(self, reason: str, model: str):
        self.reason, self.model, self.last_usage = reason, model, Usage()

    def complete_json(self, system, user, schema, images=None):
        raise LLMError(self.reason)


@dataclass
class Validation:
    file_id: str
    target_folder: str
    new_name: str
    decision: str  # accepted | edited | alternative_chosen | auto (rangé sans relecture : pas d'apprentissage)


@dataclass
class Prepared:
    batch: Batch
    report: SimulationReport
    validations: list[Validation]

    @property
    def needs_confirmation(self) -> bool:
        """Plus d'un fichier ou création de dossiers : la simulation DOIT être montrée à l'utilisateur."""
        return len(self.validations) > 1 or any(op.action == "mkdir" for op in self.batch.ops)


AUTO_MIN_CONFIDENCE = 0.8  # rangement automatique (réglage) : seulement les propositions « sûres »
READY_MIN_CONFIDENCE = 0.6  # bouton du widget : tous les fichiers « prêts » (sous ce seuil : « à vérifier »)


@dataclass
class AutoReport:
    """Résultat d'un rangement automatique : fichiers rangés, et ceux laissés pour avis (avec la raison)."""

    done: list[QueueItem] = field(default_factory=list)
    left: list[tuple[QueueItem, str]] = field(default_factory=list)


def archive_older_versions(batch: Batch, proposal, root: Path, folder: str, convention: Convention,
                           file_id: str) -> None:
    """Versions précédentes -> <dossier>/_versions/ (même lot, donc même simulation et même annulation)."""
    if folder != proposal.target_folder or not convention.versions.keep_older_in_subfolder:
        return
    for older in proposal.older_versions:
        path = Path(older)
        if path.exists():
            batch.move(Choice(path, root, f"{folder}/{convention.versions.subfolder_name}", path.name,
                              {"file_id": file_id, "version_archive": True}))


class BinService:
    def __init__(self, settings: Settings, db: Database | None = None, provider_factory=make_provider):
        self.settings = settings
        self.db = db or Database(settings.db_path)
        self.queue = QueueStore(self.db)
        self._provider_factory = provider_factory
        self._contexts: dict[str, ProposeContext] = {}
        self._convention: tuple[str, float, Convention] | None = None
        self._lock = threading.RLock()

    # --- réglages -----------------------------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return load_config(self.db)

    def update_config(self, config: AppConfig) -> None:
        save_config(self.db, config)
        with self._lock:
            self._contexts.clear()
            self._convention = None

    def convention(self) -> Convention:
        path = Path(self.config.convention_path)
        if not self.config.convention_path:
            raise BinError("Aucun fichier de convention : choisis-en un dans les réglages.")
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            raise BinError(f"Fichier de convention introuvable : {path}") from exc
        with self._lock:
            if not self._convention or self._convention[:2] != (str(path), mtime):
                try:
                    self._convention = (str(path), mtime, load_convention(path))
                except ConventionError as exc:
                    raise BinError(str(exc)) from exc
                self._contexts.clear()
            return self._convention[2]

    def ai_settings(self) -> Settings:
        """Réglages du fournisseur d'IA choisi dans l'application (sinon celui du fichier .env)."""
        cfg = self.config
        if cfg.provider and cfg.provider != self.settings.provider:
            return self.settings.for_provider(cfg.provider, cfg.model or None)
        return self.settings

    def excluded(self) -> list[str]:
        return [*self.convention().excluded_paths, *self.config.local_excluded]

    def executor(self) -> Executor:
        roots = self.config.root_paths()
        if not roots:
            raise BinError("Aucune racine configurée : ajoute un dossier de référence dans les réglages.")
        return Executor(roots, self.settings.journal_dir, self.excluded(), settings=self.settings)

    def root_for(self, path: Path) -> Path:
        """Racine qui contient le fichier, sinon racine du même volume, sinon la première."""
        roots = self.config.root_paths()
        if not roots:
            raise BinError("Aucune racine configurée : ajoute un dossier de référence dans les réglages.")
        for root in roots:
            if is_within(path, root):
                return root
        for root in roots:
            try:
                if root.exists() and restore.same_volume(path, root):
                    return root
            except OSError:
                continue
        return roots[0]

    def context(self, root: Path) -> ProposeContext:
        key = str(Path(root).resolve())
        with self._lock:
            if key not in self._contexts:
                settings = self.ai_settings()
                try:
                    llm = self._provider_factory(settings, self.config.model or None)
                except LLMError as exc:
                    llm = _NoLLM(str(exc), settings.model)
                self._contexts[key] = make_context(Path(root), self.convention(), llm, self.settings, self.db)
            return self._contexts[key]

    # --- dépôt dans la corbeille --------------------------------------------------------------

    def drop(self, path: Path) -> QueueItem:
        """« Jette » un fichier : il est déplacé (journalisé) dans le dossier tampon de sa racine."""
        path = Path(path)
        root = self.root_for(path)
        if is_within(path, root / STAGING_DIRNAME):
            raise BinError(f"« {path.name} » est déjà dans la corbeille.")
        matcher = ExclusionMatcher(self.excluded())
        try:
            check_processable(path, root if is_within(path, root) else None, matcher)
        except NotProcessable as exc:
            raise BinError(str(exc)) from exc
        executor = self.executor()
        with self._lock:  # dépôts simultanés : un seul à la fois (rapide : simple déplacement)
            batch = executor.batch()
            stage = batch.stage(path, root)
            report = executor.simulate(batch.ops)
            if not report.ok:
                raise BinError(" ; ".join(p for ps in report.problems.values() for p in ps))
            result = executor.execute(batch.ops)
        if stage.status != "done":
            raise BinError(stage.error or "Dépôt impossible.")
        item = QueueItem(file_id=new_id("f"), root=str(root), original_path=str(path),
                         staged_path=str(stage.destination), stage_operation_id=stage.operation_id)
        self.queue.upsert(item)
        log.info("staged %s -> %s (batch %s)", path, stage.destination, result.batch_id)
        return item

    def analyze(self, file_id: str) -> QueueItem:
        """Produit la proposition d'un fichier en attente (appelé en arrière-plan)."""
        item = self.queue.get(file_id)
        if item is None:
            raise BinError("Fichier introuvable dans la file d'attente.")
        staged = Path(item.staged_path)
        if not staged.exists():
            item.status, item.error = "error", "Le fichier n'est plus dans le dossier tampon."
            self.queue.upsert(item)
            return item
        try:
            proposal = propose(extract(staged), self.context(Path(item.root)))
            proposal.file_id = item.file_id
            item.proposal, item.status, item.error = proposal, "ready", None
        except BinError as exc:
            item.status, item.error = "error", str(exc)
        self.queue.upsert(item)
        return item

    def pending(self) -> list[QueueItem]:
        return self.queue.active()

    def recover(self) -> list[QueueItem]:
        """Au lancement : fichiers dont l'analyse a été interrompue (à relancer)."""
        return [i for i in self.queue.active() if i.status == "analyzing" or (i.status == "ready" and not i.proposal)]

    # --- validation -----------------------------------------------------------------------------

    def prepare(self, validations: list[Validation]) -> Prepared:
        """Planifie et simule le rangement ; la simulation est journalisée (« simulated »)."""
        executor = self.executor()
        batch = executor.batch()
        for v in validations:
            item = self.queue.get(v.file_id)
            if item is None or not item.proposal:
                raise BinError("Proposition introuvable pour ce fichier.")
            p = item.proposal
            meta = {
                "file_id": v.file_id, "decision": v.decision, "prompt_version": p.prompt_version, "model": p.model,
                "ai_proposal": {"target_folder": p.target_folder, "new_name": p.new_name, "confidence": p.confidence},
                "final_choice": {"target_folder": v.target_folder, "new_name": v.new_name},
            }
            archive_older_versions(batch, p, Path(item.root), v.target_folder, self.convention(), v.file_id)
            batch.move(Choice(Path(item.staged_path), Path(item.root), v.target_folder, v.new_name, meta))
        return Prepared(batch, executor.simulate(batch.ops), validations)

    def commit(self, prepared: Prepared) -> ExecutionReport:
        """Exécute un lot préparé ; met à jour la file d'attente et l'apprentissage."""
        result = self.executor().execute(prepared.batch.ops)
        by_file = {op.meta.get("file_id"): op for op in prepared.batch.ops
                   if op.action == "move" and not op.meta.get("version_archive")}
        for v in prepared.validations:
            op = by_file.get(v.file_id)
            if op and op.status == "done":
                self.queue.set_status(v.file_id, "done")
                self._after_placement(v, op)
            else:
                self.queue.set_status(v.file_id, "ready", op.error if op else "Opération introuvable.")
        return result

    def auto_file(self, file_ids: list[str] | None = None, min_confidence: float = AUTO_MIN_CONFIDENCE) -> AutoReport:
        """Range sans intervention les propositions assez sûres, un fichier par lot.

        Comme pour un rangement manuel, chaque fichier est simulé d'abord. Un fichier qui demande la création
        d'un dossier, ou dont la simulation signale un problème, n'est PAS rangé : il attend l'avis de
        l'utilisateur (section 3.1 : création de dossiers et lots passent par une simulation montrée).
        """
        report = AutoReport()
        with self._lock:  # analyses terminées en même temps : un seul rangement automatique à la fois
            for item in self.pending():
                if file_ids is not None and item.file_id not in file_ids:
                    continue
                p = item.proposal
                if item.status == "analyzing":
                    continue
                if item.status != "ready" or not p or p.manual or not p.target_folder or not p.new_name:
                    report.left.append((item, "à ranger à la main"))
                    continue
                if p.confidence < min_confidence:
                    report.left.append((item, "confiance trop faible"))
                    continue
                try:
                    prepared = self.prepare([Validation(item.file_id, p.target_folder, p.new_name, "auto")])
                except BinError as exc:
                    report.left.append((item, str(exc)))
                    continue
                if not prepared.report.ok:
                    report.left.append((item, " ; ".join(x for xs in prepared.report.problems.values() for x in xs)))
                    continue
                if prepared.needs_confirmation:
                    report.left.append((item, "un nouveau dossier serait créé"))
                    continue
                self.commit(prepared)
                after = self.queue.get(item.file_id)
                if after and after.status == "done":
                    report.done.append(after)
                else:
                    report.left.append((item, (after.error if after else None) or "rangement impossible"))
        log.info("auto_file: %d rangé(s), %d laissé(s)", len(report.done), len(report.left))
        return report

    def _after_placement(self, v: Validation, op) -> None:
        """Apprentissage : enregistre la décision, mémorise l'emplacement (signal implicite), résume les règles."""
        item = self.queue.get(v.file_id)
        if not item or not item.proposal:
            return
        try:
            convention = self.convention()
            original = Path(item.original_path).name
            record_correction(self.db, convention, original, item.proposal.excerpt, item.proposal.client_hint,
                              item.proposal, v.target_folder, op.destination.name, v.decision)
            remember_placement(self.db, op.operation_id, op.destination, Path(item.root), v.target_folder,
                               op.destination.name, original, item.proposal.client_hint)
            if v.decision not in ("accepted", "auto"):
                maybe_summarize(self.db, self.context(Path(item.root)).llm)
        except Exception:
            log.exception("learning hook failed")

    def check_implicit_corrections(self) -> int:
        """Au lancement : fichiers rangés par TriBin puis déplacés à la main (14 jours)."""
        try:
            return check_moved_files(self.db, self.convention())
        except BinError:
            return 0

    def return_to_origin(self, file_id: str) -> str:
        """Renvoie le fichier à son emplacement d'origine (= annulation de l'opération « stage »)."""
        item = self.queue.get(file_id)
        if item is None or not item.stage_operation_id:
            raise BinError("Fichier introuvable dans la file d'attente.")
        results = self.executor().undo(operation_id=item.stage_operation_id)
        done = [r for r in results if r["status"] == "undone"]
        if not done:
            raise BinError(results[0]["message"] if results else "Annulation impossible.")
        self.queue.set_status(file_id, "returned")
        if item.proposal and not item.proposal.manual:
            try:
                record_correction(self.db, self.convention(), Path(item.original_path).name, item.proposal.excerpt,
                                  item.proposal.client_hint, item.proposal, "", "", "rejected")
            except Exception:
                log.exception("could not record rejection")
        return done[0]["message"] or "Fichier renvoyé à son emplacement d'origine."
