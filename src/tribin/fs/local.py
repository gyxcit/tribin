"""Implémentation FileStore pour le disque local et les lecteurs réseau (NAS).

Les primitives refusent toujours d'écraser : c'est une seconde barrière derrière safety/executor.py.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from tribin.fs.base import FileStat

CHUNK = 1024 * 1024


def exists_case_insensitive(path: Path) -> Path | None:
    """Renvoie le chemin existant qui désigne le même fichier, en ignorant casse et forme Unicode."""
    from tribin.fs.filters import nfc

    if path.exists():
        return path
    parent = path.parent
    if not parent.is_dir():
        return None
    target = nfc(path.name).casefold()
    try:
        for entry in os.scandir(parent):
            if nfc(entry.name).casefold() == target:
                return Path(entry.path)
    except OSError:
        return None
    return None


class LocalFileStore:
    """Accès au système de fichiers local (y compris montages réseau et chemins UNC)."""

    def list_dir(self, path: Path) -> list[Path]:
        return sorted(Path(e.path) for e in os.scandir(path))

    def stat(self, path: Path) -> FileStat:
        st = os.stat(path)
        return FileStat(size=st.st_size, mtime=st.st_mtime, ctime=getattr(st, "st_birthtime", st.st_ctime),
                        is_dir=os.path.isdir(path), device=st.st_dev)

    def read_bytes(self, path: Path, limit: int | None = None) -> bytes:
        with open(path, "rb") as fh:
            return fh.read(limit if limit is not None else -1)

    def exists(self, path: Path) -> bool:
        return exists_case_insensitive(path) is not None

    def make_dir(self, path: Path) -> None:
        path.mkdir(parents=False, exist_ok=False)

    def move(self, src: Path, dst: Path) -> None:
        if self.exists(dst):
            raise FileExistsError(f"La destination existe déjà : {dst}")
        os.rename(src, dst)  # vérification faite juste avant (os.rename écrase sous macOS)

    def copy(self, src: Path, dst: Path) -> None:
        if self.exists(dst):
            raise FileExistsError(f"La destination existe déjà : {dst}")
        with open(src, "rb") as fin, open(dst, "xb") as fout:  # "x" : création exclusive, jamais d'écrasement
            shutil.copyfileobj(fin, fout, CHUNK)
        shutil.copystat(src, dst)

    def same_volume(self, a: Path, b: Path) -> bool:
        def device(p: Path) -> int:
            while not p.exists():
                p = p.parent
            return os.stat(p).st_dev

        return device(Path(a)) == device(Path(b))
