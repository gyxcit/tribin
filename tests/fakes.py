"""Faux fournisseurs d'IA pour les tests (aucun appel réseau)."""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from pathlib import Path

from tribin.llm.base import LLMError, Usage
from tribin.models import LLMProposal


class FakeLLM:
    """Renvoie la réponse produite par `answer(user_prompt)` ; enregistre les prompts reçus.

    `tool_script` : appels d'outil à rejouer avant de répondre, sous la forme [(nom, arguments), …] ; chaque réponse
    de l'outil est gardée dans `tool_results`. `answer` reçoit le message utilisateur ; s'il accepte un second
    paramètre, il reçoit aussi la liste des réponses d'outil."""

    def __init__(self, answer: Callable[..., LLMProposal | Exception], model: str = "fake-model",
                 tool_script: list[tuple[str, dict]] | None = None):
        self.model = model
        self.answer = answer
        self.last_usage = Usage()
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.images: list[list[bytes] | None] = []
        self.tools: list[list[dict] | None] = []
        self.tool_script = tool_script or []
        self.tool_results: list[str] = []

    def complete_json(self, system, user, schema, images=None, tools=None, call_tool=None):
        self.prompts.append(user)
        self.systems.append(system)
        self.images.append(images)
        self.tools.append(tools)
        results = []
        if tools and call_tool is not None:
            for name, arguments in self.tool_script:
                results.append(call_tool(name, arguments))
        self.tool_results = results
        self.last_usage = Usage(100, 50, 0.0001)
        try:
            result = self.answer(user, results)
        except TypeError:
            result = self.answer(user)
        if isinstance(result, Exception):
            raise result
        return result


def original_name(prompt: str) -> str:
    return re.search(r"Nom d'origine : (.+)", prompt).group(1).strip()


def oracle(testset: Path) -> FakeLLM:
    """IA « parfaite » : répond le dossier attendu de expected.csv."""
    with open(testset / "expected.csv", encoding="utf-8") as fh:
        expected = {r["file"]: r["expected_folder"] for r in csv.DictReader(fh)}

    def answer(prompt: str) -> LLMProposal:
        folder = expected[original_name(prompt)]
        return LLMProposal(target_folder=folder, description="Document test", confidence=0.9, reasoning="oracle")

    return FakeLLM(answer)


def fixed(**kw) -> FakeLLM:
    def answer(prompt: str) -> LLMProposal | Exception:
        if "error" in kw:
            return kw["error"]
        return LLMProposal(**kw)

    return FakeLLM(answer)


__all__ = ["FakeLLM", "LLMError", "fixed", "oracle", "original_name"]
