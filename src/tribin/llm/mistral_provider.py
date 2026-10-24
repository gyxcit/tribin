"""Fournisseur Mistral AI : même contrat que les autres fournisseurs (JSON strict validé par pydantic)."""

from __future__ import annotations

import base64
import json
import logging
import threading

from pydantic import ValidationError

from tribin.llm.anthropic_provider import extract_json
from tribin.llm.base import LLMError, T, Usage

log = logging.getLogger(__name__)

DEFAULT_MODEL = "mistral-small-latest"
TIMEOUT_MS = 60_000
MAX_TOKENS = 4000


class MistralProvider:
    """Appels à l'API Mistral via le SDK officiel mistralai."""

    def __init__(self, api_key: str, model: str, client=None):
        self.model = model
        self._local = threading.local()
        if client is None:
            from mistralai.client import Mistral
            from mistralai.client.utils.retries import BackoffStrategy, RetryConfig

            # Erreurs réseau et limites de débit : nouvelles tentatives avec attente progressive (~3 essais).
            retries = RetryConfig("backoff", BackoffStrategy(1000, 8000, 2.0, 20000), retry_connection_errors=True,
                                  status_codes_override=["429", "5XX"])
            client = Mistral(api_key=api_key, timeout_ms=TIMEOUT_MS, retry_config=retries)
        self.client = client

    @property
    def last_usage(self) -> Usage:
        if not hasattr(self._local, "usage"):
            self._local.usage = Usage()
        return self._local.usage

    @last_usage.setter
    def last_usage(self, value: Usage) -> None:
        self._local.usage = value

    @staticmethod
    def _response_format(schema: type[T] | None):
        from mistralai.client.models import JSONSchema, ResponseFormat

        if schema is None:
            return ResponseFormat(type="json_object")
        return ResponseFormat(type="json_schema", json_schema=JSONSchema(
            name="proposition", schema_definition=schema.model_json_schema(), strict=False))

    def _call(self, messages: list[dict], schema: type[T] | None):
        from mistralai.client.errors import HTTPValidationError, NoResponseError, SDKError

        try:
            return self.client.chat.complete(model=self.model, messages=messages, max_tokens=MAX_TOKENS,
                                             response_format=self._response_format(schema))
        except SDKError as exc:
            code = getattr(exc, "status_code", 0)
            if code in (401, 403):
                raise LLMError("Clé API Mistral refusée : vérifie la clé dans les réglages.") from exc
            if code == 402:
                raise LLMError("Crédits Mistral épuisés : vérifie la facturation sur console.mistral.ai.") from exc
            if code == 404:
                raise LLMError(f"Modèle Mistral introuvable : {self.model}. Vérifie le nom du modèle.") from exc
            if code == 429:
                raise LLMError("Limite de requêtes Mistral atteinte : réessaie dans quelques minutes.") from exc
            if code == 400:
                raise
            raise LLMError(f"Erreur du service Mistral ({code}).") from exc
        except HTTPValidationError as exc:
            raise LLMError("Requête refusée par Mistral (format invalide).") from exc
        except (NoResponseError, OSError) as exc:
            raise LLMError("Impossible de joindre le service Mistral : vérifie la connexion internet.") from exc

    @staticmethod
    def _text(response) -> str:
        content = response.choices[0].message.content if response.choices else ""
        if isinstance(content, list):  # morceaux de contenu
            return "".join(getattr(chunk, "text", "") or "" for chunk in content)
        return content or ""

    def complete_json(self, system: str, user: str, schema: type[T], images: list[bytes] | None = None) -> T:
        from mistralai.client.errors import SDKError

        content: list[dict] = [{"type": "text", "text": user}]
        for image in images or []:
            content.append({"type": "image_url",
                            "image_url": "data:image/jpeg;base64," + base64.standard_b64encode(image).decode("ascii")})
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        self.last_usage = Usage()
        use_schema: type[T] | None = schema
        for attempt in range(2):  # une seule nouvelle tentative si le JSON est invalide
            try:
                response = self._call(messages, use_schema)
            except SDKError as exc:  # 400 : schéma refusé par le modèle -> mode JSON simple
                if use_schema is not None and attempt == 0:
                    log.warning("Mistral refused the response schema, retrying in JSON mode: %s", exc)
                    use_schema = None
                    continue
                raise LLMError("Requête refusée par Mistral (400).") from exc
            usage = getattr(response, "usage", None)
            if usage is not None:
                self.last_usage.input_tokens += usage.prompt_tokens or 0
                self.last_usage.output_tokens += usage.completion_tokens or 0
            text = self._text(response)
            try:
                return schema.model_validate_json(extract_json(text))
            except (ValidationError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise LLMError("Réponse de Mistral invalide après une nouvelle tentative.") from exc
                messages = [*messages, {"role": "assistant", "content": text or "(vide)"},
                            {"role": "user", "content": f"Ta réponse n'est pas un JSON valide : {exc}. "
                                                        "Renvoie uniquement l'objet JSON corrigé."}]
        raise LLMError("Réponse de Mistral invalide.")
