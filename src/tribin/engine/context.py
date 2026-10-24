"""Assemble le contexte de proposition à partir des réglages (profil, cartographie, apprentissage, versions)."""

from __future__ import annotations

from pathlib import Path

from tribin.config import Settings
from tribin.convention.loader import Convention
from tribin.db import Database
from tribin.engine.candidates import select_candidates
from tribin.engine.clients import detect_client
from tribin.engine.proposer import ProposeContext
from tribin.learning.corrections import similar_examples
from tribin.learning.rules_store import list_rules
from tribin.llm.base import LLMProvider
from tribin.mapping.profiles import FolderProfile, light_update, load_profiles, save_profiles
from tribin.mapping.scanner import scan_root


def read_profile(settings: Settings) -> str:
    try:
        return settings.profile_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_profiles(db: Database, root: Path, convention: Convention) -> list[FolderProfile]:
    """Profils de la racine : cartographie complète la première fois, mise à jour légère ensuite."""
    fresh = scan_root(root, convention)
    if not load_profiles(db, root):
        save_profiles(db, root, fresh)
    else:
        light_update(db, root, fresh)
    return load_profiles(db, root)


def make_context(root: Path, convention: Convention, llm: LLMProvider, settings: Settings,
                 db: Database | None = None) -> ProposeContext:
    """Contexte complet utilisé par la ligne de commande et l'application."""
    db = db or Database(settings.db_path)
    profiles = ensure_profiles(db, root, convention)
    ctx = ProposeContext(root=Path(root), convention=convention, llm=llm, profile=read_profile(settings))
    ctx.client_detector = lambda info: detect_client(info, convention)
    ctx.candidate_provider = lambda info, hint: select_candidates(info, profiles, convention, hint)
    ctx.examples_provider = lambda info, hint: similar_examples(db, info, hint)
    ctx.rules_provider = lambda: [r.text for r in list_rules(db, only_enabled=True)]
    return ctx
