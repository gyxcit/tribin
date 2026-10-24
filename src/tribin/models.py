"""Modèles pydantic partagés entre les modules."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

LOW_CONFIDENCE = 0.6


class FileInfo(BaseModel):
    """Informations extraites d'un fichier (section 6.2)."""

    file_id: str
    path: str
    name: str
    extension: str  # en minuscules, avec le point ; "" si aucune ; ".tar.gz" conservé
    size: int
    created: dt.datetime
    modified: dt.datetime
    origin_folder: str
    mime: str
    text: str = ""
    images: list[bytes] = Field(default_factory=list, exclude=True)  # miniatures JPEG <= 1024 px
    metadata: dict[str, str] = Field(default_factory=dict)
    extraction_error: str | None = None


class NameFields(BaseModel):
    """Éléments du nom de fichier, renvoyés par l'IA puis complétés par le code."""

    date: dt.date | None = None
    client: str | None = None
    project_code: str | None = None
    project_name: str | None = None
    category: str | None = None
    description: str = ""
    version: int | None = None


class Alternative(BaseModel):
    target_folder: str
    new_name: str
    reasoning: str


class Proposal(BaseModel):
    """Proposition de rangement (section 6.3)."""

    file_id: str
    source_path: str = ""
    target_folder: str  # relatif à la racine, séparateur "/"
    folder_is_new: bool = False
    new_name: str
    fields: NameFields
    confidence: float
    reasoning: str
    alternatives: list[Alternative] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    prompt_version: str
    model: str
    manual: bool = False  # True : échec de l'IA, « à traiter manuellement »
    new_category: str | None = None  # mode personnel : catégorie créée pour ce fichier (dossier à créer)
    client_hint: str | None = None
    excerpt: str = ""  # début du contenu extrait (apprentissage)
    older_versions: list[str] = Field(default_factory=list)  # versions précédentes à ranger dans _versions/
    cost_usd: float = 0.0
    duration_s: float = 0.0

    @property
    def needs_review(self) -> bool:
        """« À vérifier » si la confiance est faible ou si la proposition est manuelle."""
        return self.manual or self.confidence < LOW_CONFIDENCE


# --- Réponse attendue de l'IA (section 8) ---------------------------------------------------


class LLMAlternative(BaseModel):
    target_folder: str
    category: str | None = None
    description: str | None = None
    reasoning: str = ""


class LLMProposal(BaseModel):
    """Objet JSON renvoyé par le modèle. Le nom final est construit par le code, jamais par l'IA."""

    client: str | None = None
    project_code: str | None = None
    project_name: str | None = None
    category: str | None = None
    date: str | None = None  # AAAA-MM-JJ
    description: str = ""
    target_folder: str
    folder_is_new: bool = False
    confidence: float = 0.5
    reasoning: str = ""
    alternatives: list[LLMAlternative] = Field(default_factory=list)
