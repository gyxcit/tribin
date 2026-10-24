"""Détection du client (section 6.3, étape 2) : un indice pour l'IA, jamais une certitude."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from tribin.convention.loader import Convention
from tribin.convention.naming import strip_accents
from tribin.models import FileInfo

THRESHOLD = 88


def normalize_text(text: str) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces."""
    return re.sub(r"[^a-z0-9]+", " ", strip_accents(text).lower()).strip()


def detect_client(info: FileInfo, convention: Convention) -> str | None:
    """Code du client le plus probable d'après le nom, le dossier d'origine et le contenu du fichier."""
    haystack = normalize_text(f"{info.name} {info.origin_folder} {info.text[:3000]} {' '.join(info.metadata.values())}")
    if not haystack:
        return None
    padded = f" {haystack} "
    best_code, best_score = None, 0.0
    for client in convention.clients:
        score = 0.0
        for term in {client.code, client.name, *client.aliases}:
            norm = normalize_text(term)
            if len(norm) < 3:
                continue
            hits = padded.count(f" {norm} ")
            if hits:
                score = max(score, 100 + min(hits, 5) + len(norm) / 100)
            elif len(norm) >= 5:
                score = max(score, fuzz.partial_ratio(norm, haystack))
        if score > best_score:
            best_code, best_score = client.code, score
    return best_code if best_score >= THRESHOLD else None
