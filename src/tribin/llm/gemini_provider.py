"""Fournisseur Google Gemini : même contrat que AnthropicProvider (JSON strict validé par pydantic)."""

from __future__ import annotations

import json
import logging
import threading

from pydantic import ValidationError

from tribin.llm.anthropic_provider import extract_json
from tribin.llm.base import LLMError, T, Usage

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
TIMEOUT_MS = 60_000
ATTEMPTS = 3  # tentatives réseau / limites de débit, avec attente progressive (géré par le SDK)


class GeminiProvider:
    """Appels à l'API Gemini via le SDK officiel google-genai."""

    def __init__(self, api_key: str, model: str, client=None):
        self.model = model
        self._local = threading.local()
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
                timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=ATTEMPTS)))
        self.client = client

    @property
    def last_usage(self) -> Usage:
        if not hasattr(self._local, "usage"):
            self._local.usage = Usage()
        return self._local.usage

    @last_usage.setter
    def last_usage(self, value: Usage) -> None:
        self._local.usage = value

    def _call(self, system: str, contents: list, schema: type[T] | None):
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema() if schema is not None else None,
        )
        try:
            return self.client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.ClientError as exc:
            if exc.code in (401, 403):
                raise LLMError("Clé API Gemini refusée : vérifie la clé dans les réglages.") from exc
            if exc.code == 402:
                raise LLMError("Crédits Gemini épuisés : recharge le compte dans Google AI Studio "
                               "(https://ai.studio/projects, rubrique facturation).") from exc
            if exc.code == 404:
                raise LLMError(f"Modèle Gemini introuvable : {self.model}. Vérifie le nom du modèle.") from exc
            if exc.code == 429:
                raise LLMError("Limite de requêtes Gemini atteinte : réessaie dans quelques minutes.") from exc
            raise
        except errors.ServerError as exc:
            raise LLMError(f"Erreur du service Gemini ({exc.code}).") from exc
        except errors.APIError as exc:
            raise LLMError(f"Erreur du service Gemini ({exc.code}).") from exc
        except OSError as exc:
            raise LLMError("Impossible de joindre le service Gemini : vérifie la connexion internet.") from exc

    def complete_json(self, system: str, user: str, schema: type[T], images: list[bytes] | None = None) -> T:
        from google.genai import errors, types

        parts = [types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images or []]
        contents: list = [types.Content(role="user", parts=[*parts, types.Part(text=user)])]
        self.last_usage = Usage()
        use_schema: type[T] | None = schema
        for attempt in range(2):  # une seule nouvelle tentative si le JSON est invalide
            try:
                response = self._call(system, contents, use_schema)
            except errors.ClientError as exc:
                if exc.code == 400 and use_schema is not None and attempt == 0:
                    log.warning("Gemini refused the response schema, retrying without it: %s", exc)
                    use_schema = None  # le prompt décrit déjà le format attendu
                    continue
                raise LLMError(f"Requête refusée par Gemini ({exc.code}).") from exc
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                self.last_usage.input_tokens += usage.prompt_token_count or 0
                self.last_usage.output_tokens += usage.candidates_token_count or 0
            text = response.text or ""
            if not text:
                feedback = getattr(response, "prompt_feedback", None)
                if feedback is not None and getattr(feedback, "block_reason", None):
                    raise LLMError("Gemini a refusé de traiter ce fichier.")
            try:
                return schema.model_validate_json(extract_json(text))
            except (ValidationError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise LLMError("Réponse de Gemini invalide après une nouvelle tentative.") from exc
                contents = [*contents, types.Content(role="model", parts=[types.Part(text=text or "(vide)")]),
                            types.Content(role="user", parts=[types.Part(
                                text=f"Ta réponse n'est pas un JSON valide : {exc}. Renvoie uniquement l'objet JSON corrigé.")])]
        raise LLMError("Réponse de Gemini invalide.")
