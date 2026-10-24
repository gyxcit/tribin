"""Fournisseur Anthropic (Claude) : sortie JSON structurée validée par pydantic."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading

import anthropic
from pydantic import ValidationError

from tribin.llm.base import LLMError, T, Usage

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


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def extract_json(text: str) -> str:
    """Isole l'objet JSON d'une réponse (retire d'éventuelles balises de code)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


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

    def _call(self, system: str, messages: list[dict], schema: type[T]):
        try:
            return self.client.messages.parse(
                model=self.model, max_tokens=MAX_TOKENS, system=system, messages=messages, output_format=schema,
            )
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

    def complete_json(self, system: str, user: str, schema: type[T], images: list[bytes] | None = None) -> T:
        messages: list[dict] = [{"role": "user", "content": self._content(user, images)}]
        self.last_usage = Usage()
        for attempt in range(2):  # une seule nouvelle tentative si le JSON est invalide
            try:
                response = self._call(system, messages, schema)
            except ValidationError as exc:
                log.warning("structured output failed validation: %s", exc)
                if attempt == 0:
                    continue
                raise LLMError("Réponse de l'IA invalide.") from exc
            usage = response.usage
            self.last_usage.input_tokens += usage.input_tokens
            self.last_usage.output_tokens += usage.output_tokens
            self.last_usage.cost_usd += estimate_cost(self.model, usage.input_tokens, usage.output_tokens)
            if response.stop_reason == "refusal":
                raise LLMError("L'IA a refusé de traiter ce fichier.")
            parsed = getattr(response, "parsed_output", None)
            if parsed is not None:
                return parsed
            text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
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
