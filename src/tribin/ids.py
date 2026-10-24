"""Identifiants triables par date (ULID, 26 caractères Crockford base32)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """Nouvel ULID : 48 bits d'horodatage (ms) + 80 bits aléatoires."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    """Identifiant préfixé, ex. new_id("op") -> "op_01JA7X..."."""
    return f"{prefix}_{ulid()}"
