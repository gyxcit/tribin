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
