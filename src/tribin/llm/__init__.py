"""Fabrique du fournisseur d'IA configuré."""

from __future__ import annotations

from tribin.config import Settings
from tribin.llm.base import LLMError, LLMProvider


def make_provider(settings: Settings, model: str | None = None) -> LLMProvider:
    """Crée le fournisseur d'IA à partir des réglages. Lève LLMError si la clé API manque."""
    if not settings.api_key:
        raise LLMError("Clé API Anthropic manquante : renseigne ANTHROPIC_API_KEY dans le fichier .env "
                       "(ou dans les réglages de l'application).")
    from tribin.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(api_key=settings.api_key, model=model or settings.model)
