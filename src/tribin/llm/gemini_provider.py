"""Fournisseur Google Gemini : même contrat que AnthropicProvider (JSON strict validé par pydantic, outils)."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

from pydantic import ValidationError

from tribin.llm.anthropic_provider import extract_json
from tribin.llm.base import MAX_TOOL_CALLS, LLMError, T, Usage

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

    def _call(self, system: str, contents: list, schema: type[T] | None, tools: list | None = None,
              tool_mode: str | None = None):
        """Un appel. Avec des outils : déclarations de fonctions, SANS `response_mime_type` JSON (incompatibles)."""
        from google.genai import errors, types

        if tools:
            config = types.GenerateContentConfig(
                system_instruction=system, tools=tools,
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=tool_mode or "AUTO")),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
        else:
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

    def _account(self, response) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.last_usage.input_tokens += usage.prompt_token_count or 0
            self.last_usage.output_tokens += usage.candidates_token_count or 0
            self.last_usage.cached_input_tokens += getattr(usage, "cached_content_token_count", 0) or 0

    @staticmethod
    def _declare(tools: list[dict]) -> list:
        from google.genai import types

        return [types.Tool(function_declarations=[types.FunctionDeclaration(
            name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"])]) for t in tools]

    def _run_tools(self, system: str, contents: list, tools: list[dict], call_tool: Callable[[str, dict], str]):
        """Boucle d'appels de fonction (parts `function_call` / `function_response`) jusqu'à la réponse finale."""
        from google.genai import types

        declared = self._declare(tools)
        done, mode = 0, "AUTO"
        for _ in range(MAX_TOOL_CALLS + 2):
            response = self._call(system, contents, None, declared, mode)
            self._account(response)
            calls = list(getattr(response, "function_calls", None) or [])
            if not calls:
                return response
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                done += 1
                result = call_tool(call.name, dict(call.args or {}))
                try:
                    payload = json.loads(result)
                except json.JSONDecodeError:
                    payload = {"resultat": result}
                parts.append(types.Part.from_function_response(name=call.name, response={"result": payload}))
            contents.append(types.Content(role="user", parts=parts))
            if done > MAX_TOOL_CALLS:
                mode = "NONE"
        raise LLMError("Gemini n'a pas conclu après ses appels d'outil.")

    def complete_json(self, system: str, user: str, schema: type[T], images: list[bytes] | None = None,
                      tools: list[dict] | None = None, call_tool: Callable[[str, dict], str] | None = None) -> T:
        from google.genai import errors, types

        parts = [types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images or []]
        contents: list = [types.Content(role="user", parts=[*parts, types.Part(text=user)])]
        self.last_usage = Usage()
        use_schema: type[T] | None = schema
        with_tools = bool(tools) and call_tool is not None
        for attempt in range(2):  # une seule nouvelle tentative si le JSON est invalide
            try:
                if with_tools:
                    response = self._run_tools(system, contents, tools, call_tool)
                else:
                    response = self._call(system, contents, use_schema)
                    self._account(response)
            except errors.ClientError as exc:
                if exc.code == 400 and use_schema is not None and attempt == 0 and not with_tools:
                    log.warning("Gemini refused the response schema, retrying without it: %s", exc)
                    use_schema = None  # le prompt décrit déjà le format attendu
                    continue
                raise LLMError(f"Requête refusée par Gemini ({exc.code}).") from exc
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
