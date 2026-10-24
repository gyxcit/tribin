"""Interface d'accès aux fichiers (section 5.3). Toute opération sur les fichiers passe par un FileStore."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class FileStat:
    size: int
    mtime: float
    ctime: float
    is_dir: bool
    device: int


class FileStore(Protocol):
    def list_dir(self, path: Path) -> list[Path]: ...

    def stat(self, path: Path) -> FileStat: ...

    def read_bytes(self, path: Path, limit: int | None = None) -> bytes: ...

    def exists(self, path: Path) -> bool: ...

    def make_dir(self, path: Path) -> None: ...

    def move(self, src: Path, dst: Path) -> None:
        """Déplacement sur le même volume ; échoue si `dst` existe."""
        ...

    def copy(self, src: Path, dst: Path) -> None:
        """Copie ; échoue si `dst` existe."""
        ...

    def same_volume(self, a: Path, b: Path) -> bool: ...
