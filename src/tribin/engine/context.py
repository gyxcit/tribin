"""Assemble le contexte de proposition à partir des réglages (profil, cartographie, apprentissage, versions)."""

from __future__ import annotations

from pathlib import Path

from tribin.config import Settings
from tribin.convention.loader import Convention
from tribin.engine.proposer import ProposeContext
from tribin.llm.base import LLMProvider


def read_profile(settings: Settings) -> str:
    try:
        return settings.profile_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def make_context(root: Path, convention: Convention, llm: LLMProvider, settings: Settings) -> ProposeContext:
    """Contexte complet utilisé par la ligne de commande et l'application."""
    return ProposeContext(root=Path(root), convention=convention, llm=llm, profile=read_profile(settings))
