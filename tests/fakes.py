"""Faux fournisseurs d'IA pour les tests (aucun appel réseau)."""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from pathlib import Path

from tribin.llm.base import LLMError, Usage
from tribin.models import LLMProposal


class FakeLLM:
    """Renvoie la réponse produite par `answer(user_prompt)` ; enregistre les prompts reçus."""

    def __init__(self, answer: Callable[[str], LLMProposal | Exception], model: str = "fake-model"):
        self.model = model
        self.answer = answer
        self.last_usage = Usage()
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.images: list[list[bytes] | None] = []

    def complete_json(self, system, user, schema, images=None):
        self.prompts.append(user)
        self.systems.append(system)
        self.images.append(images)
        self.last_usage = Usage(100, 50, 0.0001)
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
