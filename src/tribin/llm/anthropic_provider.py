"""Fournisseur Anthropic (Claude) : sortie JSON structurée validée par pydantic ; outils (appels de fonction)."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from collections.abc import Callable

import anthropic
from pydantic import ValidationError

from tribin.llm.base import MAX_TOOL_CALLS, LLMError, T, Usage

log = logging.getLogger(__name__)

# Prix publics en dollars par million de jetons (entrée, sortie), pour estimer le coût par fichier.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
MAX_TOKENS = 8000
TIMEOUT_S = 60.0
MAX_RETRIES = 2  # le SDK réessaie avec attente progressive : 3 tentatives au total
CACHE_WRITE_FACTOR = 1.25  # écriture dans le cache de prompt : +25 % sur ces jetons
CACHE_READ_FACTOR = 0.10  # lecture depuis le cache : 10 % du prix d'entrée


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0) -> float:
    """Coût estimé ; `input_tokens` ne compte pas les jetons écrits dans le cache ni lus depuis le cache."""
    price_in, price_out = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    inputs = input_tokens * price_in + cache_write * price_in * CACHE_WRITE_FACTOR + cache_read * price_in * CACHE_READ_FACTOR
    return (inputs + output_tokens * price_out) / 1_000_000


def extract_json(text: str) -> str:
    """Isole l'objet JSON d'une réponse (retire d'éventuelles balises de code)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")


class AnthropicProvider:
    """Appels à l'API Claude via le SDK officiel."""

    def __init__(self, api_key: str, model: str, client: anthropic.Anthropic | None = None):
        self.model = model
        self._local = threading.local()  # usage par fil d'exécution (appels en parallèle)
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=MAX_RETRIES)

    @property
    def last_usage(self) -> Usage:
        """Consommation du dernier appel fait par ce fil d'exécution."""
        if not hasattr(self._local, "usage"):
            self._local.usage = Usage()
        return self._local.usage

    @last_usage.setter
    def last_usage(self, value: Usage) -> None:
        self._local.usage = value

    def _content(self, user: str, images: list[bytes] | None) -> list[dict]:
        blocks: list[dict] = []
        for image in images or []:
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.standard_b64encode(image).decode("ascii")}})
        blocks.append({"type": "text", "text": user})
        return blocks

    @staticmethod
    def _system_blocks(system: str) -> list[dict]:
        """Le `system` (consignes + contexte de rangement, identique d'un fichier à l'autre) est marqué pour le cache
        de prompt : lu depuis le cache à partir du deuxième fichier d'un lot."""
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def _guard(self, method, **params):
        """Un appel à l'API, avec les erreurs traduites pour l'utilisateur."""
        try:
            return method(**params)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Clé API refusée : vérifie la clé dans les réglages.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Modèle introuvable : {self.model}. Vérifie le nom du modèle dans les réglages.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Limite de requêtes atteinte : réessaie dans quelques minutes.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Impossible de joindre le service d'IA : vérifie la connexion internet.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Erreur du service d'IA ({exc.status_code}).") from exc

    def _call(self, system: str, messages: list[dict], schema: type[T]):
        """Sans outil : sortie structurée (validée par le SDK)."""
        return self._guard(self.client.messages.parse, model=self.model, max_tokens=MAX_TOKENS,
                           system=self._system_blocks(system), messages=messages, output_format=schema)

    def _account(self, usage) -> None:
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.last_usage.input_tokens += usage.input_tokens + cache_write + cache_read
        self.last_usage.cached_input_tokens += cache_read
        self.last_usage.output_tokens += usage.output_tokens
        self.last_usage.cost_usd += estimate_cost(self.model, usage.input_tokens, usage.output_tokens,
                                                  cache_write, cache_read)

    def _run_tools(self, system: str, messages: list[dict], tools: list[dict], call_tool: Callable[[str, dict], str]):
        """Boucle d'appels d'outil : réponse → outil(s) → résultats → nouvelle réponse, jusqu'à la réponse finale.

        Au-delà du budget (MAX_TOOL_CALLS, tenu par l'appelant qui répond « budget épuisé »), les outils ne sont plus
        proposés (`tool_choice = none`). La réponse finale est lue en JSON texte (`output_format` et `tools` ne se
        combinent pas dans `messages.parse`)."""
        declared = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools]
        done, choice = 0, {"type": "auto"}
        for _ in range(MAX_TOOL_CALLS + 2):
            response = self._guard(self.client.messages.create, model=self.model, max_tokens=MAX_TOKENS,
                                   system=self._system_blocks(system), messages=messages, tools=declared,
                                   tool_choice=choice)
            self._account(response.usage)
            uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if not uses:
                return response
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for use in uses:  # plusieurs appels dans une réponse : tous les résultats dans un seul message
                done += 1
                results.append({"type": "tool_result", "tool_use_id": use.id,
                                "content": call_tool(use.name, dict(use.input or {}))})
            messages.append({"role": "user", "content": results})
            if done > MAX_TOOL_CALLS:
                choice = {"type": "none"}
        raise LLMError("L'IA n'a pas conclu après ses appels d'outil.")

    def complete_json(self, system: str, user: str, schema: type[T], images: list[bytes] | None = None,
                      tools: list[dict] | None = None, call_tool: Callable[[str, dict], str] | None = None) -> T:
        messages: list[dict] = [{"role": "user", "content": self._content(user, images)}]
        self.last_usage = Usage()
        with_tools = bool(tools) and call_tool is not None
        for attempt in range(2):  # une seule nouvelle tentative si le JSON est invalide
            try:
                if with_tools:
                    response = self._run_tools(system, messages, tools, call_tool)
                else:
                    response = self._call(system, messages, schema)
                    self._account(response.usage)
            except ValidationError as exc:
                log.warning("structured output failed validation: %s", exc)
                if attempt == 0:
                    continue
                raise LLMError("Réponse de l'IA invalide.") from exc
            if response.stop_reason == "refusal":
                raise LLMError("L'IA a refusé de traiter ce fichier.")
            parsed = None if with_tools else getattr(response, "parsed_output", None)
            if parsed is not None:
                return parsed
            text = _text_of(response)
            try:
                return schema.model_validate_json(extract_json(text))
            except (ValidationError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise LLMError("Réponse de l'IA invalide après une nouvelle tentative.") from exc
                messages += [
                    {"role": "assistant", "content": text or "(vide)"},
                    {"role": "user", "content": f"Ta réponse n'est pas un JSON valide : {exc}. "
                                                "Renvoie uniquement l'objet JSON corrigé."},
                ]
        raise LLMError("Réponse de l'IA invalide.")
