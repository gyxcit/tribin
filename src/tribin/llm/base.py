"""Interface LLMProvider (section 5.4) : permet de changer de fournisseur (Anthropic aujourd'hui, Ollama plus tard)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MAX_TOOL_CALLS = 3  # appels d'outil par fichier, tous outils confondus (skill v2, § 2.4) ; au-delà : « budget épuisé »


class LLMError(RuntimeError):
    """Échec d'un appel à l'IA (réseau, quota, réponse invalide). Message destiné à l'utilisateur."""


@dataclass
class Usage:
    input_tokens: int = 0  # jetons d'entrée, cache compris
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached_input_tokens: int = 0  # part lue depuis le cache de prompt (0 si le fournisseur ne le dit pas)


class LLMProvider(Protocol):
    model: str
    last_usage: Usage

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        images: list[bytes] | None = None,
        tools: list[dict] | None = None,
        call_tool: Callable[[str, dict], str] | None = None,
    ) -> T:
        """Renvoie la réponse du modèle validée par `schema`. Lève LLMError en cas d'échec.

        `tools` : déclarations (`name`, `description`, `input_schema`), traduites dans le format du fournisseur ;
        `call_tool(nom, arguments) -> str` (JSON) exécute un appel. Le fournisseur boucle (réponse → appel d'outil →
        résultat → nouvelle réponse) jusqu'à la réponse finale ou au budget (MAX_TOOL_CALLS), puis valide le JSON."""
        ...
