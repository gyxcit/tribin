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
    # Mode actif (« work » ou « personal » ; vide : déduit de la convention) et, pour chaque mode, ses propres
    # dossiers à ranger, dossiers exclus et convention : changer de mode ne mélange pas perso et travail.
    mode: str = ""
    by_mode: dict[str, dict] = Field(default_factory=dict)
    auto_file: bool = False  # ranger tout seul les propositions sûres ; les autres attendent un avis
    auto_min_confidence: float = 0.8  # seuil du rangement automatique (réglable de 60 à 95 %)
    hotkey: bool = True  # Ctrl + Alt + T : envoie la sélection de l'Explorateur à TriBin (Windows)
    onboarding_done: bool = False
    privacy_accepted: bool = False

    def root_paths(self) -> list[Path]:
        return [Path(r) for r in self.roots]

    def remember_mode(self, mode: str) -> None:
        """Mémorise les dossiers et la convention actuels comme ceux du mode `mode`."""
        self.mode = mode
        self.by_mode[mode] = {"roots": list(self.roots), "local_excluded": list(self.local_excluded),
                              "convention_path": self.convention_path}

    def mode_values(self, mode: str) -> dict:
        """Dossiers et convention enregistrés pour `mode` (vides s'il n'a jamais été utilisé)."""
        saved = self.by_mode.get(mode) or {}
        return {"roots": list(saved.get("roots", [])), "local_excluded": list(saved.get("local_excluded", [])),
                "convention_path": saved.get("convention_path", "")}


def load_config(db: Database) -> AppConfig:
    return AppConfig.model_validate(db.get_setting("app_config", {}) or {})


def save_config(db: Database, config: AppConfig) -> None:
    db.set_setting("app_config", config.model_dump())
