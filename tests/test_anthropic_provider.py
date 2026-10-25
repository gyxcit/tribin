"""Tests du fournisseur Anthropic avec un faux client (aucun appel réseau)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx2 as httpx
import pytest
from anthropic import APIConnectionError
from pydantic import BaseModel

from tribin.llm.anthropic_provider import AnthropicProvider, estimate_cost, extract_json
from tribin.llm.base import LLMError


class Schema(BaseModel):
    value: int


def response(parsed=None, text="", stop="end_turn"):
    return SimpleNamespace(parsed_output=parsed, content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def parse(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    create = parse  # boucle d'outils : messages.create (réponse lue en JSON texte)


def provider(responses):
    messages = FakeMessages(responses)
    return AnthropicProvider("k", "claude-haiku-5-5", client=SimpleNamespace(messages=messages)), messages


def test_parsed_output_returned_and_cost():
    p, msgs = provider([response(parsed=Schema(value=3))])
    assert p.complete_json("sys", "user", Schema, images=[b"\xff\xd8jpeg"]).value == 3
    content = msgs.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[-1]["text"] == "user"
    assert p.last_usage.cost_usd == pytest.approx(estimate_cost("claude-haiku-5-5", 1000, 100))


def test_invalid_json_retried_once_then_ok():
    p, msgs = provider([response(text="pas du json"), response(text='```json\n{"value": 5}\n```')])
    assert p.complete_json("s", "u", Schema).value == 5
    assert len(msgs.calls) == 2 and "JSON valide" in msgs.calls[1]["messages"][-1]["content"]


def test_invalid_json_twice_fails_cleanly():
    p, _ = provider([response(text="non"), response(text="toujours non")])
    with pytest.raises(LLMError):
        p.complete_json("s", "u", Schema)


def test_network_error_mapped():
    err = APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    p, _ = provider([err])
    with pytest.raises(LLMError, match="connexion"):
        p.complete_json("s", "u", Schema)


def test_refusal():
    p, _ = provider([response(stop="refusal")])
    with pytest.raises(LLMError, match="refusé"):
        p.complete_json("s", "u", Schema)


def test_extract_json():
    assert extract_json('Voici : {"a": 1} fin') == '{"a": 1}'


def test_system_is_cached_and_cache_tokens_counted():
    r = response(parsed=Schema(value=3))
    r.usage = SimpleNamespace(input_tokens=200, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=1500)
    p, msgs = provider([r])
    p.complete_json("consignes", "fichier", Schema)
    system = msgs.calls[0]["system"]
    assert system == [{"type": "text", "text": "consignes", "cache_control": {"type": "ephemeral"}}]
    assert p.last_usage.input_tokens == 1700 and p.last_usage.cached_input_tokens == 1500
    assert p.last_usage.cost_usd == pytest.approx(estimate_cost("claude-haiku-5-5", 200, 100, cache_read=1500))
    assert estimate_cost("claude-haiku-5-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.01)


def test_tool_loop_then_final_json():
    """Appel d'outil → résultat → réponse finale ; au-delà du budget, les outils ne sont plus proposés."""
    from tribin.llm.base import MAX_TOOL_CALLS

    def tool_use(n):
        r = response(text="")
        r.content = [SimpleNamespace(type="tool_use", id=f"tu_{n}", name="lister_dossiers", input={"chemin": "" if n == 1 else "Etudes"})]
        r.stop_reason = "tool_use"
        return r

    seen = []

    def call_tool(name, arguments):
        seen.append((name, arguments))
        return '{"dossiers": []}'

    p, msgs = provider([tool_use(1), tool_use(2), response(text='{"value": 9}')])
    tools = [{"name": "lister_dossiers", "description": "liste", "input_schema": {"type": "object", "properties": {}}}]
    assert p.complete_json("sys", "user", Schema, tools=tools, call_tool=call_tool).value == 9
    assert seen == [("lister_dossiers", {"chemin": ""}), ("lister_dossiers", {"chemin": "Etudes"})]
    first, last = msgs.calls[0], msgs.calls[-1]
    assert first["tools"] == tools and first["tool_choice"] == {"type": "auto"} and "output_format" not in first
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    history = last["messages"]
    assert history[1]["role"] == "assistant" and history[2]["content"][0] == {"type": "tool_result", "tool_use_id": "tu_1", "content": '{"dossiers": []}'}
    assert p.last_usage.input_tokens == 3000  # trois appels comptés

    # 4 appels : le dernier reçoit « budget épuisé » puis tool_choice = none
    p, msgs = provider([tool_use(1), tool_use(2), tool_use(3), tool_use(4), response(text='{"value": 1}')])
    assert p.complete_json("s", "u", Schema, tools=tools, call_tool=call_tool).value == 1
    assert msgs.calls[-1]["tool_choice"] == {"type": "none"} and msgs.calls[-2]["tool_choice"] == {"type": "auto"}
    assert MAX_TOOL_CALLS == 3
