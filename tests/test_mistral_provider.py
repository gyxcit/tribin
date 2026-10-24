"""Fournisseur Mistral, testé avec un faux client (aucun appel réseau)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx2
import pytest
from pydantic import BaseModel

pytest.importorskip("mistralai.client")
from mistralai.client.errors import SDKError  # noqa: E402

from tribin.config import load_settings, model_for  # noqa: E402
from tribin.llm import make_provider  # noqa: E402
from tribin.llm.base import LLMError  # noqa: E402
from tribin.llm.mistral_provider import MistralProvider  # noqa: E402


class Schema(BaseModel):
    value: int


def response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                           usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30))


def sdk_error(code: int) -> SDKError:
    raw = httpx2.Response(code, request=httpx2.Request("POST", "https://api.mistral.ai/v1/chat/completions"))
    return SDKError("erreur", raw, "{}")


class FakeChat:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def provider(results):
    chat = FakeChat(results)
    return MistralProvider("k", "mistral-small-latest", client=SimpleNamespace(chat=chat)), chat


def test_json_answer_with_image_and_schema():
    p, chat = provider([response('{"value": 3}')])
    assert p.complete_json("système", "question", Schema, images=[b"\xff\xd8img"]).value == 3
    call = chat.calls[0]
    assert call["model"] == "mistral-small-latest"
    assert call["messages"][0] == {"role": "system", "content": "système"}
    content = call["messages"][1]["content"]
    assert content[0]["text"] == "question" and content[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert call["response_format"].type == "json_schema"
    assert p.last_usage.input_tokens == 120


def test_chunked_content_and_invalid_json_retry():
    chunks = [SimpleNamespace(text='{"val'), SimpleNamespace(text='ue": 9}')]
    p, chat = provider([response("pas du json"), response(chunks)])
    assert p.complete_json("s", "u", Schema).value == 9
    assert [m["role"] for m in chat.calls[1]["messages"]] == ["system", "user", "assistant", "user"]


def test_schema_refused_falls_back_to_json_mode():
    p, chat = provider([sdk_error(400), response('{"value": 1}')])
    assert p.complete_json("s", "u", Schema).value == 1
    assert chat.calls[1]["response_format"].type == "json_object"


@pytest.mark.parametrize("code,needle", [(401, "Clé API Mistral refusée"), (402, "Crédits Mistral épuisés"),
                                         (404, "introuvable"), (429, "Limite de requêtes"), (503, "Erreur du service")])
def test_errors_are_explained_in_french(code, needle):
    p, _ = provider([sdk_error(code)])
    with pytest.raises(LLMError, match=needle):
        p.complete_json("s", "u", Schema)


def test_provider_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBIN_PROVIDER", "mistral")
    monkeypatch.setenv("TRIBIN_MODEL", "gemini-flash-latest")  # modèle d'un autre fournisseur : ignoré
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-de-test")
    s = load_settings(env_file=tmp_path / "absent.env")
    assert s.provider == "mistral" and s.model == "mistral-medium-latest" and s.api_key == "cle-de-test"
    assert isinstance(make_provider(s), MistralProvider)
    assert model_for("mistral", "magistral-medium-latest") == "magistral-medium-latest"


def test_missing_mistral_key_is_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBIN_PROVIDER", "mistral")
    s = load_settings(env_file=tmp_path / "absent.env")
    with pytest.raises(LLMError, match="MISTRAL_API_KEY"):
        make_provider(s)
