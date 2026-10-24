"""Opérations planifiées et lots (préparation du travail de safety/executor.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from tribin.config import ARCHIVE_DIRNAME, STAGING_DIRNAME, STAGING_SUBDIR
from tribin.convention.naming import unique_name
from tribin.ids import new_id

FILE_ACTIONS = {"stage", "move", "rename", "archive"}


@dataclass
class Operation:
    action: str  # stage | mkdir | move | rename | archive
    destination: Path
    root: Path
    source: Path | None = None
    operation_id: str = field(default_factory=lambda: new_id("op"))
    batch_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # ai_proposal, final_choice, decision, prompt_version, model, file_id
    status: str = "planned"
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    size: int | None = None
    hash_before: str | None = None
    hash_after: str | None = None
    already_existed: bool = False

    def describe(self) -> str:
        if self.action == "mkdir":
            return f"Créer le dossier {self.destination}"
        verb = {"stage": "Mettre dans la corbeille", "move": "Ranger", "rename": "Renommer",
                "archive": "Archiver"}[self.action]
        return f"{verb} : {self.source} → {self.destination}"

    def record(self, status: str, user: str, **extra) -> dict:
        """Ligne de journal complète (la dernière ligne d'une opération suffit à la décrire)."""
        rec = {
            "operation_id": self.operation_id, "batch_id": self.batch_id, "user": user, "action": self.action,
            "status": status, "source": str(self.source) if self.source else None,
            "destination": str(self.destination), "root": str(self.root), "size": self.size,
            "hash_before": self.hash_before, "hash_after": self.hash_after, "error": self.error,
            "already_existed": self.already_existed or None, **self.meta, **extra,
        }
        return {k: v for k, v in rec.items() if v is not None}


@dataclass
class Choice:
    """Choix validé par l'utilisateur pour un fichier."""

    source: Path
    root: Path
    target_folder: str  # relatif à la racine, "/" comme séparateur
    new_name: str
    meta: dict = field(default_factory=dict)


class Batch:
    """Lot d'opérations ; tient compte des dossiers et noms déjà prévus dans le lot."""

    def __init__(self) -> None:
        self.id = new_id("b")
        self.ops: list[Operation] = []
        self._dirs: dict[str, Operation] = {}
        self._names: dict[str, set[str]] = {}

    def _add(self, op: Operation) -> Operation:
        op.batch_id = self.id
        self.ops.append(op)
        return op

    def _taken(self, folder: Path) -> set[str]:
        key = os.path.normcase(str(folder))
        if key not in self._names:
            try:
                self._names[key] = {e.name for e in os.scandir(folder)}
            except OSError:
                self._names[key] = set()
        return self._names[key]

    def mkdirs(self, root: Path, rel: str) -> list[str]:
        """Opérations mkdir pour chaque niveau manquant de root/rel. Renvoie l'id de la dernière (dépendance)."""
        deps: list[str] = []
        current = Path(root)
        for part in [p for p in rel.replace("\\", "/").split("/") if p]:
            current = current / part
            key = os.path.normcase(str(current))
            if key in self._dirs:
                deps = [self._dirs[key].operation_id]
                continue
            if current.is_dir():
                continue
            op = self._add(Operation("mkdir", current, Path(root), depends_on=list(deps)))
            self._dirs[key] = op
            deps = [op.operation_id]
        return deps

    def file_op(self, action: str, source: Path, root: Path, folder: Path, name: str, meta: dict | None = None,
                deps: list[str] | None = None) -> Operation:
        final = unique_name(name, self._taken(folder) - ({source.name} if source.parent == folder else set()))
        self._taken(folder).add(final)
        op = Operation(action, folder / final, Path(root), source=Path(source), depends_on=deps or [], meta=meta or {})
        if final != name:
            op.notes.append(f"« {name} » existe déjà : renommé en « {final} »")
        return self._add(op)

    def move(self, choice: Choice, action: str = "move") -> Operation:
        deps = self.mkdirs(choice.root, choice.target_folder)
        folder = Path(choice.root).joinpath(*[p for p in choice.target_folder.split("/") if p])
        return self.file_op(action, choice.source, choice.root, folder, choice.new_name, choice.meta, deps)

    def stage(self, source: Path, root: Path, meta: dict | None = None) -> Operation:
        rel = f"{STAGING_DIRNAME}/{STAGING_SUBDIR}"
        return self.move(Choice(Path(source), Path(root), rel, Path(source).name, meta or {}), action="stage")

    def archive(self, source: Path, root: Path, meta: dict | None = None) -> Operation:
        return self.move(Choice(Path(source), Path(root), ARCHIVE_DIRNAME, Path(source).name, meta or {}), action="archive")

    def rename(self, source: Path, root: Path, new_name: str, meta: dict | None = None) -> Operation:
        source = Path(source)
        return self.file_op("rename", source, root, source.parent, new_name, meta)
