"""Interface LLMProvider (section 5.4) : permet de changer de fournisseur (Anthropic aujourd'hui, Ollama plus tard)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Échec d'un appel à l'IA (réseau, quota, réponse invalide). Message destiné à l'utilisateur."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class LLMProvider(Protocol):
    model: str
    last_usage: Usage

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        images: list[bytes] | None = None,
    ) -> T:
        """Renvoie la réponse du modèle validée par `schema`. Lève LLMError en cas d'échec."""
        ...
