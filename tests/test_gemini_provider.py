"""Fournisseur Gemini, testé avec un faux client (aucun appel réseau)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

pytest.importorskip("google.genai")
from google.genai import errors  # noqa: E402

from tribin.config import load_settings, model_for  # noqa: E402
from tribin.llm import make_provider  # noqa: E402
from tribin.llm.base import LLMError  # noqa: E402
from tribin.llm.gemini_provider import GeminiProvider  # noqa: E402


class Schema(BaseModel):
    value: int


def response(text: str):
    return SimpleNamespace(text=text, prompt_feedback=None,
                           usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=20))


class FakeModels:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def provider(results):
    models = FakeModels(results)
    return GeminiProvider("k", "gemini-flash-latest", client=SimpleNamespace(models=models)), models


def test_json_answer_with_image_and_schema():
    p, models = provider([response('{"value": 4}')])
    assert p.complete_json("système", "question", Schema, images=[b"\xff\xd8img"]).value == 4
    _, contents, config = models.calls[0]
    assert config.system_instruction == "système" and config.response_mime_type == "application/json"
    assert config.response_json_schema["properties"]["value"]["type"] == "integer"
    parts = contents[0].parts
    assert parts[0].inline_data.mime_type == "image/jpeg" and parts[-1].text == "question"
    assert p.last_usage.input_tokens == 100


def test_invalid_json_retried_once():
    p, models = provider([response("pas du json"), response('```json\n{"value": 7}\n```')])
    assert p.complete_json("s", "u", Schema).value == 7
    retry_contents = models.calls[1][1]
    assert [c.role for c in retry_contents] == ["user", "model", "user"]


def test_schema_refused_falls_back_without_schema():
    p, models = provider([errors.ClientError(400, {"error": {"message": "schema"}}), response('{"value": 1}')])
    assert p.complete_json("s", "u", Schema).value == 1
    assert models.calls[1][2].response_json_schema is None


@pytest.mark.parametrize("code,needle", [(402, "Crédits Gemini épuisés"), (403, "Clé API Gemini refusée"),
                                         (429, "Limite de requêtes"), (404, "introuvable")])
def test_errors_are_explained_in_french(code, needle):
    p, _ = provider([errors.ClientError(code, {"error": {"message": "x"}})])
    with pytest.raises(LLMError, match=needle):
        p.complete_json("s", "u", Schema)


def test_provider_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBIN_PROVIDER", "gemini")
    monkeypatch.setenv("TRIBIN_MODEL", "claude-haiku-5-5")  # modèle d'un autre fournisseur : ignoré
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-test")
    s = load_settings(env_file=tmp_path / "absent.env")
    assert s.provider == "gemini" and s.model == "gemini-flash-latest" and s.api_key == "cle-de-test"
    assert isinstance(make_provider(s), GeminiProvider)
    assert model_for("anthropic", "gemini-2.5-flash") == "claude-haiku-5-5"


def test_missing_gemini_key_is_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBIN_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    import tribin.config as cfg

    monkeypatch.setattr(cfg, "read_api_key", lambda provider="anthropic": None)
    s = cfg.load_settings(env_file=tmp_path / "absent.env")
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        make_provider(s)
