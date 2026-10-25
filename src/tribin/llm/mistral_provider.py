"""Fournisseur Mistral AI : même contrat que les autres fournisseurs (JSON strict validé par pydantic, outils)."""

from __future__ import annotations

import base64
import json
import logging
import threading
from collections.abc import Callable

from pydantic import ValidationError

from tribin.llm.anthropic_provider import extract_json
from tribin.llm.base import MAX_TOOL_CALLS, LLMError, T, Usage

log = logging.getLogger(__name__)

DEFAULT_MODEL = "mistral-medium-latest"  # choisi après évaluation (meilleure calibration de la confiance)
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

    def _call(self, messages: list[dict], schema: type[T] | None, tools: list[dict] | None = None,
              tool_choice: str | None = None):
        """Un appel. Avec des outils : `tool_choice` auto puis none, et pas de `response_format` pendant la boucle."""
        from mistralai.client.errors import HTTPValidationError, NoResponseError, SDKError

        params: dict = {"model": self.model, "messages": messages, "max_tokens": MAX_TOKENS}
        if tools:
            params["tools"], params["tool_choice"] = tools, tool_choice or "auto"
        else:
            params["response_format"] = self._response_format(schema)
        try:
            return self.client.chat.complete(**params)
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

    def _account(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage.input_tokens += usage.prompt_tokens or 0
            self.last_usage.output_tokens += usage.completion_tokens or 0

    @staticmethod
    def _declare(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in tools]

    def _run_tools(self, messages: list[dict], tools: list[dict], call_tool: Callable[[str, dict], str]):
        """Boucle d'appels d'outil (messages `role = tool` avec `tool_call_id`) jusqu'à la réponse finale."""
        declared = self._declare(tools)
        done, choice = 0, "auto"
        for _ in range(MAX_TOOL_CALLS + 2):
            response = self._call(messages, None, declared, choice)
            self._account(response)
            message = response.choices[0].message if response.choices else None
            calls = list(getattr(message, "tool_calls", None) or [])
            if not calls:
                return response
            messages.append({"role": "assistant", "content": self._text(response) or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments if isinstance(c.function.arguments, str)
                    else json.dumps(c.function.arguments or {}, ensure_ascii=False)}} for c in calls]})
            for c in calls:
                done += 1
                arguments = c.function.arguments
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                messages.append({"role": "tool", "name": c.function.name, "tool_call_id": c.id,
                                 "content": call_tool(c.function.name, dict(arguments or {}))})
            if done > MAX_TOOL_CALLS:
                choice = "none"
        raise LLMError("Mistral n'a pas conclu après ses appels d'outil.")

    def complete_json(self, system: str, user: str, schema: type[T], images: list[bytes] | None = None,
                      tools: list[dict] | None = None, call_tool: Callable[[str, dict], str] | None = None) -> T:
        from mistralai.client.errors import SDKError

        content: list[dict] = [{"type": "text", "text": user}]
        for image in images or []:
            content.append({"type": "image_url",
                            "image_url": "data:image/jpeg;base64," + base64.standard_b64encode(image).decode("ascii")})
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        self.last_usage = Usage()
        use_schema: type[T] | None = schema
        with_tools = bool(tools) and call_tool is not None
        for attempt in range(2):  # une seule nouvelle tentative si le JSON est invalide
            try:
                if with_tools:
                    response = self._run_tools(messages, tools, call_tool)
                else:
                    response = self._call(messages, use_schema)
                    self._account(response)
            except SDKError as exc:  # 400 : schéma refusé par le modèle -> mode JSON simple
                if use_schema is not None and attempt == 0 and not with_tools:
                    log.warning("Mistral refused the response schema, retrying in JSON mode: %s", exc)
                    use_schema = None
                    continue
                raise LLMError("Requête refusée par Mistral (400).") from exc
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
