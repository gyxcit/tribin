"""Exécution sécurisée : plan / simulate / execute / undo (sections 3, 6.5 et 7).

TOUS les déplacements de fichiers de l'application passent par ce module. Règles :
jamais de suppression, jamais d'écrasement, journal écrit AVANT chaque opération, périmètre des racines,
zones exclues intouchables, simulation qui passe par exactement les mêmes vérifications que l'exécution.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from tribin.config import SandboxViolation, Settings, assert_in_sandbox, get_settings, is_within
from tribin.convention.naming import MAX_PATH_LENGTH, is_valid_name, unique_name
from tribin.fs.filters import EXCLUDED_ZONE_MESSAGE, ExclusionMatcher, is_ignored_name
from tribin.fs.local import exists_case_insensitive
from tribin.safety import restore
from tribin.safety.hashing import maybe_hash
from tribin.safety.journal import Journal
from tribin.safety.operations import FILE_ACTIONS, Batch, Choice, Operation

log = logging.getLogger(__name__)

LOCKED_MESSAGE = "Fichier ouvert dans une autre application : ferme-le puis réessaie."
NOT_OVERWRITTEN = "rien n'est écrasé"  # fin de la remarque « nom déjà pris » (retirée puis recalculée à chaque simulation)


@dataclass
class SimulationReport:
    batch_id: str
    operations: list[Operation]
    problems: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(self.problems.values())

    def lines(self) -> list[str]:
        out = []
        for op in self.operations:
            mark = "✗" if self.problems.get(op.operation_id) else "✓"
            out.append(f"{mark} {op.describe()}")
            out += [f"    ! {p}" for p in self.problems.get(op.operation_id, [])]
            out += [f"    · {n}" for n in op.notes]
        return out


@dataclass
class ExecutionReport:
    batch_id: str
    operations: list[Operation]

    @property
    def done(self) -> list[Operation]:
        return [op for op in self.operations if op.status == "done"]

    @property
    def failed(self) -> list[Operation]:
        return [op for op in self.operations if op.status in {"failed", "skipped"}]


class _Virtual:
    """État virtuel du disque pendant une simulation (dossiers créés, fichiers déplacés)."""

    def __init__(self) -> None:
        self.dirs: set[str] = set()
        self.files: set[str] = set()
        self.gone: set[str] = set()

    @staticmethod
    def key(p: Path) -> str:
        return os.path.normcase(os.path.abspath(p)).casefold()

    def is_dir(self, p: Path) -> bool:
        return self.key(p) in self.dirs or p.is_dir()

    def file_exists(self, p: Path) -> bool:
        k = self.key(p)
        if k in self.gone:
            return False
        return k in self.files or exists_case_insensitive(p) is not None


class Executor:
    """Point unique d'exécution des opérations sur les fichiers."""

    def __init__(self, roots: list[Path], journal_dir: Path | None = None, excluded: list[str] | None = None,
                 settings: Settings | None = None, user: str | None = None):
        self.settings = settings or get_settings()
        self.roots = [Path(r).resolve() for r in roots]
        self.journal = Journal(journal_dir or self.settings.journal_dir)
        self.matcher = ExclusionMatcher(excluded or [])
        self.user = user or self.settings.user
        self._after_copy = None  # crochet de test : simuler une interruption juste après la copie

    # --- planification ------------------------------------------------------------------------

    def batch(self) -> Batch:
        return Batch()

    def plan(self, choices: list[Choice]) -> list[Operation]:
        """Transforme des choix validés en opérations (création des dossiers manquants comprise)."""
        batch = self.batch()
        for choice in choices:
            batch.move(choice)
        return batch.ops

    # --- vérifications communes à la simulation et à l'exécution ------------------------------

    def _guard(self, path: Path) -> None:
        assert_in_sandbox(path, self.settings)

    def _root_of(self, path: Path) -> Path | None:
        return next((r for r in self.roots if is_within(path, r)), None)

    def check(self, op: Operation, virtual: _Virtual | None = None) -> list[str]:
        """Problèmes bloquants pour cette opération ; ajoute des remarques dans op.notes."""
        v = virtual or _Virtual()
        problems: list[str] = []
        try:
            self._guard(op.destination)
            if op.source:
                self._guard(op.source)
        except SandboxViolation as exc:
            return [str(exc)]
        root = self._root_of(op.destination)
        if root is None or not is_within(op.destination, op.root):
            return [f"Destination hors des racines déclarées : {op.destination}"]
        if not is_within(op.destination.parent, root):
            return [f"Destination hors des racines déclarées : {op.destination}"]
        if self.matcher.is_excluded(op.destination, root):
            problems.append(f"Destination dans une zone exclue : {op.destination}")
        if not v.is_dir(op.destination.parent):
            problems.append(f"Dossier de destination introuvable : {op.destination.parent}")
        if len(str(op.destination)) > MAX_PATH_LENGTH:
            problems.append(f"Chemin trop long ({len(str(op.destination))} caractères, maximum {MAX_PATH_LENGTH}).")
        if op.action == "mkdir":
            if v.is_dir(op.destination):
                op.already_existed = True
            elif v.file_exists(op.destination):
                problems.append(f"Un fichier porte déjà ce nom : {op.destination}")
            return problems
        problems += self._check_file(op, v, root)
        return problems

    def _check_file(self, op: Operation, v: _Virtual, root: Path) -> list[str]:
        problems: list[str] = []
        src = op.source
        if src is None:
            return ["Source manquante."]
        if src.is_symlink():
            return [f"« {src.name} » est un lien symbolique : refusé."]
        if not (v.file_exists(src) and (src.is_file() or v.key(src) in v.files)):
            return [f"« {src.name} » n'est plus dans « {src.parent.name} » : il a sans doute déjà été rangé, "
                    "déplacé ou supprimé. Rien ne sera fait."]
        if is_ignored_name(src.name):
            problems.append(f"« {src.name} » est un fichier système ou temporaire : refusé.")
        src_root = self._root_of(src)  # la source peut venir d'ailleurs (bureau…) ; seule la destination est bornée
        if src_root is not None and self.matcher.is_excluded(src, src_root):
            problems.append(EXCLUDED_ZONE_MESSAGE)
        if not is_valid_name(op.destination.name):
            problems.append(f"Nom invalide sous Windows ou macOS : « {op.destination.name} »")
        if v.file_exists(op.destination):
            existing = {op.destination.name}
            if op.destination.parent.is_dir():
                existing |= {e.name for e in os.scandir(op.destination.parent)}
            op.notes.append(f"Un fichier « {op.destination.name} » est déjà dans ce dossier : celui-ci s'appellera "
                            f"« {unique_name(op.destination.name, existing)} » ({NOT_OVERWRITTEN}).")
        if op.destination.parent.is_dir() and not os.access(op.destination.parent, os.W_OK):
            problems.append(f"Pas le droit d'écrire dans {op.destination.parent}")
        if src.exists() and not os.access(src.parent, os.W_OK):
            problems.append(f"Pas le droit de modifier {src.parent}")
        if src.exists() and op.destination.parent.is_dir() and not restore.same_volume(src, op.destination.parent):
            free = shutil.disk_usage(op.destination.parent).free
            if free < src.stat().st_size * 1.05:
                problems.append("Espace disque insuffisant sur le volume de destination.")
        return problems

    # --- simulation ---------------------------------------------------------------------------

    def simulate(self, ops: list[Operation], journal: bool = True) -> SimulationReport:
        """Vérifie tout sans toucher aux fichiers ; inscrit les opérations au journal (statut « simulated »)."""
        report = SimulationReport(batch_id=ops[0].batch_id if ops else "", operations=ops)
        virtual = _Virtual()
        failed: set[str] = set()
        for op in ops:
            op.notes = [n for n in op.notes if NOT_OVERWRITTEN not in n]
            problems = self.check(op, virtual)
            if any(d in failed for d in op.depends_on):
                problems.append("Dépend d'une opération en erreur.")
            report.problems[op.operation_id] = problems
            if problems:
                failed.add(op.operation_id)
            elif op.action == "mkdir":
                virtual.dirs.add(virtual.key(op.destination))
            else:
                virtual.files.add(virtual.key(op.destination))
                virtual.gone.add(virtual.key(op.source))
            if journal:
                self.journal.write(op.record("simulated", self.user, error="; ".join(problems) or None))
        return report

    # --- exécution ----------------------------------------------------------------------------

    def execute(self, ops: list[Operation]) -> ExecutionReport:
        """Exécute opération par opération : journal « pending » AVANT, puis « done » ou « failed »."""
        failed: set[str] = set()
        for op in ops:
            if any(d in failed for d in op.depends_on):
                op.status, op.error = "skipped", "Ignorée : une opération dont elle dépend a échoué."
                self.journal.write(op.record("skipped", self.user))
                failed.add(op.operation_id)
                continue
            problems = self.check(op)
            if problems:
                op.status, op.error = "failed", "; ".join(problems)
                self.journal.write(op.record("failed", self.user))
                failed.add(op.operation_id)
                continue
            try:
                self._run(op)
                op.status = "done"
                self.journal.write(op.record("done", self.user))
            except Exception as exc:
                op.status = "failed"
                op.error = LOCKED_MESSAGE if isinstance(exc, PermissionError) else f"{type(exc).__name__} : {exc}"
                log.warning("operation %s failed: %s", op.operation_id, exc)
                self.journal.write(op.record("failed", self.user))
                failed.add(op.operation_id)
        return ExecutionReport(batch_id=ops[0].batch_id if ops else "", operations=ops)

    def _run(self, op: Operation) -> None:
        if op.action == "mkdir":
            if op.already_existed or op.destination.is_dir():
                op.already_existed = True
                self.journal.write(op.record("pending", self.user))
                return
            self.journal.write(op.record("pending", self.user))
            try:
                op.destination.mkdir()
            except FileExistsError:
                if not op.destination.is_dir():
                    raise
                op.already_existed = True  # créé entre-temps (autre lot) : l'annulation ne le retirera pas
            return
        src = op.source
        # Vérifier l'existence JUSTE AVANT l'opération ; collision -> suffixe _2, _3…
        if exists_case_insensitive(op.destination) is not None:
            existing = {e.name for e in os.scandir(op.destination.parent)}
            new_name = unique_name(op.destination.name, existing)
            op.notes.append(f"« {op.destination.name} » existait : renommé en « {new_name} »")
            op.destination = op.destination.with_name(new_name)
        op.size = src.stat().st_size
        cross = not restore.same_volume(src, op.destination.parent)
        op.hash_before = None if cross else maybe_hash(src, op.size)  # inter-volumes : calculé pendant la copie
        self.journal.write(op.record("pending", self.user))
        hash_before, hash_after = restore.safe_move(src, op.destination, after_copy=self._after_copy)
        if cross:
            op.hash_before, op.hash_after = hash_before, hash_after

    # --- annulation ---------------------------------------------------------------------------

    def undo(self, operation_id: str | None = None, batch_id: str | None = None, execute: bool = True) -> list[dict]:
        """Annule une opération ou un lot via restore.py (même code que le script autonome)."""
        if not (operation_id or batch_id):
            raise ValueError("Préciser une opération ou un lot.")
        return restore.undo(self.journal.dir, batch=batch_id, operation=operation_id, execute=execute,
                            user=self.user, guard=self._guard)


__all__ = ["Batch", "Choice", "ExecutionReport", "Executor", "FILE_ACTIONS", "Operation", "SimulationReport"]
