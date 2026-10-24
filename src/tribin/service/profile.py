"""Profil utilisateur issu de l'onboarding (section 6.8), stocké dans profile.md et inclus dans chaque prompt."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from tribin.llm.base import LLMError, LLMProvider

log = logging.getLogger(__name__)

QUESTIONS: list[tuple[str, str, list[str], bool]] = [
    # (clé, question, choix, choix multiple)
    ("secteur", "Ton secteur", ["Agence de pub / com", "Studio créatif", "Freelance", "Autre"], False),
    ("role", "Ton rôle", ["Créa", "Chef de projet", "Production", "Commercial / admin", "Direction", "Autre"], False),
    ("usage", "Usage", ["Personnel", "En équipe"], False),
    ("types", "Types de fichiers principaux", ["Visuels", "Documents", "Vidéo", "Admin / factures", "Mise en page", "Autre"], True),
    ("situation", "Situation", ["Une structure existe à respecter", "Structure à créer de zéro",
                                "À réorganiser (bientôt disponible)"], False),
]

PRIVACY_NOTICE = (
    "Confidentialité : pour proposer un rangement, TriBin envoie au service d'IA configuré (Anthropic) un extrait "
    "du fichier — texte tronqué à 4 000 caractères et image réduite à 1 024 pixels —, jamais le fichier complet. "
    "Aucune télémétrie. Tes réponses d'onboarding restent sur cet ordinateur."
)

PROFILE_SYSTEM = ("Tu rédiges, en français, le profil court (5 à 8 lignes) d'un utilisateur d'un outil de rangement de "
                  "fichiers, à partir de ses réponses. Le profil sert de contexte à une IA qui propose où ranger chaque "
                  "fichier. Sois factuel, sans inventer. Réponds en JSON : {\"text\": \"...\"}.")


class ProfileText(BaseModel):
    text: str


def answers_summary(answers: dict[str, object]) -> str:
    lines = []
    for key, question, _, _ in QUESTIONS:
        value = answers.get(key)
        if value:
            lines.append(f"- {question} : {', '.join(value) if isinstance(value, list) else value}")
    if answers.get("contexte"):
        lines.append(f"- Contexte : {answers['contexte']}")
    return "\n".join(lines)


def build_profile(answers: dict[str, object], llm: LLMProvider | None = None) -> str:
    """Profil rédigé par l'IA ; à défaut (pas de clé, erreur), résumé direct des réponses."""
    summary = answers_summary(answers)
    if not summary:
        return ""
    if llm is not None:
        try:
            return llm.complete_json(PROFILE_SYSTEM, f"Réponses :\n{summary}", ProfileText).text.strip()
        except LLMError as exc:
            log.warning("profile generation failed: %s", exc)
    return "Profil de l'utilisateur :\n" + summary


def save_profile(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
