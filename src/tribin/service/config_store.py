"""Réglages locaux de l'application (racines, zones exclues, convention…), stockés dans SQLite."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tribin.db import Database


class AppConfig(BaseModel):
    roots: list[str] = Field(default_factory=list)
    convention_path: str = ""
    local_excluded: list[str] = Field(default_factory=list)  # zones exclues propres à ce poste (motifs glob)
    provider: str = ""  # vide : fournisseur des réglages (.env) ; sinon "anthropic", "gemini" ou "mistral"
    model: str = ""  # vide : modèle par défaut des réglages (.env)
    auto_file: bool = False  # ranger tout seul les propositions sûres ; les autres attendent un avis
    auto_min_confidence: float = 0.8  # seuil du rangement automatique (réglable de 60 à 95 %)
    hotkey: bool = True  # Ctrl + Alt + T : envoie la sélection de l'Explorateur à TriBin (Windows)
    onboarding_done: bool = False
    privacy_accepted: bool = False

    def root_paths(self) -> list[Path]:
        return [Path(r) for r in self.roots]


def load_config(db: Database) -> AppConfig:
    return AppConfig.model_validate(db.get_setting("app_config", {}) or {})


def save_config(db: Database, config: AppConfig) -> None:
    db.set_setting("app_config", config.model_dump())
