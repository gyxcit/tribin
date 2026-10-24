"""Fabrique du fournisseur d'IA configuré (Anthropic, Gemini ou Mistral)."""

from __future__ import annotations

import logging

from tribin.config import PROVIDERS, Settings
from tribin.llm.base import LLMError, LLMProvider

KEY_HINTS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

log = logging.getLogger(__name__)


def make_provider(settings: Settings, model: str | None = None, provider: str | None = None) -> LLMProvider:
    """Crée le fournisseur d'IA à partir des réglages. Lève LLMError si la clé API manque."""
    if provider and provider != settings.provider:
        settings = settings.for_provider(provider, model)
    elif model:
        settings = settings.for_provider(settings.provider, model)
    name = settings.provider
    if name not in PROVIDERS:
        raise LLMError(f"Fournisseur d'IA inconnu : {name}.")
    if not settings.api_key:
        raise LLMError(f"Clé API {name.capitalize()} manquante : renseigne {KEY_HINTS[name]} dans le fichier .env "
                       "(ou dans les réglages de l'application).")
    if name == "mistral":
        try:
            from tribin.llm.mistral_provider import MistralProvider
        except Exception as exc:  # ImportError, ou erreur pendant le chargement du SDK (appli empaquetée)
            log.exception("chargement du fournisseur Mistral impossible")
            raise LLMError("Le module Mistral est absent de cette installation de TriBin : réinstallez TriBin (ou « uv sync » depuis les sources).") from exc
        return MistralProvider(api_key=settings.api_key, model=settings.model)
    if name == "gemini":
        try:
            from tribin.llm.gemini_provider import GeminiProvider
        except Exception as exc:  # ImportError, ou erreur pendant le chargement du SDK (appli empaquetée)
            log.exception("chargement du fournisseur Gemini impossible")
            raise LLMError("Le module Gemini est absent de cette installation de TriBin : réinstallez TriBin (ou « uv sync » depuis les sources).") from exc
        return GeminiProvider(api_key=settings.api_key, model=settings.model)
    from tribin.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(api_key=settings.api_key, model=settings.model)
