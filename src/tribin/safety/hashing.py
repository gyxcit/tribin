"""Hash SHA-256 par blocs de 1 Mo (implémentation partagée avec le script de restauration autonome)."""

from __future__ import annotations

from pathlib import Path

from tribin.safety.restore import CHUNK, sha256_file

# Au-delà, pas de hash systématique pour un déplacement sur le même volume (trop lent pour une grosse vidéo).
SAME_VOLUME_HASH_LIMIT = 50 * 1024 * 1024


def maybe_hash(path: Path, size: int) -> str | None:
    """Hash si le fichier est assez petit, sinon None (on vérifie alors taille et existence)."""
    return sha256_file(path) if size <= SAME_VOLUME_HASH_LIMIT else None


__all__ = ["CHUNK", "SAME_VOLUME_HASH_LIMIT", "maybe_hash", "sha256_file"]
