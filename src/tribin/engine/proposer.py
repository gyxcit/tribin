"""Moteur de proposition : fichier -> Proposal (section 6.3)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from tribin.config import STAGING_DIRNAME, is_within
from tribin.convention.loader import Convention
from tribin.convention.naming import build_name, clean_segment, extract_version, fit_to_path, split_extension, unique_name
from tribin.convention.structure import personal_folder_ok, fields_from_folder, folder_from_fields, matches_template
from tribin.engine.candidates import Candidate, phase1_candidates
from tribin.engine.prompts import PromptData, build_user_prompt, human_size, prompt_version, system_prompt
from tribin.engine.similar import SimilarFolder
from tribin.fs.filters import ExclusionMatcher
from tribin.llm.base import LLMError, LLMProvider
from tribin.models import Alternative, FileInfo, LLMProposal, NameFields, Proposal

log = logging.getLogger(__name__)

MAX_CLIENTS_IN_PROMPT = 30
ALTERNATIVE_CONFIDENCE_CAP = 0.55  # même valeur que dans le barème du prompt


@dataclass
class ProposeContext:
    """Tout ce dont le moteur a besoin. Les fonctions facultatives branchent les phases suivantes."""

    root: Path
    convention: Convention
    llm: LLMProvider
    profile: str = ""
    learned_rules: list[str] = field(default_factory=list)
    candidate_provider: Callable[[FileInfo, str | None], list[Candidate]] | None = None
    client_detector: Callable[[FileInfo], str | None] | None = None
    examples_provider: Callable[[FileInfo, str | None], list[str]] | None = None
    version_detector: Callable[[FileInfo, Proposal, ProposeContext], None] | None = None
    rules_provider: Callable[[], list[str]] | None = None
    similar_provider: Callable[[FileInfo], list[SimilarFolder]] | None = None
    project_folders: list[str] = field(default_factory=list)
    _phase1_cache: list[Candidate] | None = None

    def candidates(self, info: FileInfo, client_hint: str | None) -> list[Candidate]:
        if self.candidate_provider:
            return self.candidate_provider(info, client_hint)
        if self._phase1_cache is None:
            self._phase1_cache = phase1_candidates(self.root, self.convention)
        return self._phase1_cache


# Valeurs « vides » que l'IA écrit parfois en toutes lettres : jamais un nom de dossier ni un élément du nom.
PLACEHOLDERS = {"null", "none", "nil", "undefined", "nan", "unknown", "inconnu", "inconnue"}


def is_placeholder(value: str | None) -> bool:
    """Vrai pour « null », « None », « inconnu », « {client} », « <projet> »…"""
    text = (value or "").strip().strip("\"'«» ").casefold()
    return not text or text in PLACEHOLDERS or any(c in text for c in "{}<>")


def has_placeholder(folder: str) -> bool:
    return any(is_placeholder(part) for part in folder.split("/"))


def _real(value: str | None) -> str | None:
    return None if value is None or is_placeholder(value) else value


def normalize_rel(folder: str | None) -> str | None:
    """Chemin relatif propre ("A/B/C"), ou None s'il est absolu ou remonte avec « .. »."""
    if not folder:
        return ""
    text = folder.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return None
    parts = [p for p in PurePosixPath(text).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _clients_text(convention: Convention, hint: str | None) -> str:
    clients = list(convention.clients)
    if len(clients) > MAX_CLIENTS_IN_PROMPT:
        clients.sort(key=lambda c: c.code != hint)
        clients = clients[:MAX_CLIENTS_IN_PROMPT]
    return "; ".join(f"{c.code} : {c.name}" + (f" ({', '.join(c.aliases)})" if c.aliases else "") for c in clients)


def build_prompt_data(info: FileInfo, ctx: ProposeContext, hint: str | None, candidates: list[Candidate],
                      examples: list[str], similar: list[SimilarFolder] | None = None) -> PromptData:
    conv = ctx.convention
    return PromptData(
        structure_template=conv.structure.template,
        project_format=conv.structure.project_format,
        categories_with_descriptions="; ".join(f"{c.code} ({c.description})" for c in conv.structure.categories),
        clients_list=_clients_text(conv, hint),
        original_name=info.name,
        extension=info.extension,
        mime=info.mime,
        size_human=human_size(info.size),
        created=info.created.strftime("%Y-%m-%d"),
        modified=info.modified.strftime("%Y-%m-%d"),
        origin_folder=info.origin_folder,
        extracted_text=info.text,
        profile=ctx.profile,
        learned_rules=ctx.rules_provider() if ctx.rules_provider else ctx.learned_rules,
        candidate_folders=[c.render() for c in candidates],
        project_folders=ctx.project_folders,
        correction_examples=examples,
        similar_files=[s.render() for s in similar or []],
        client_hint=hint or "",
        has_image=bool(info.images),
        extra_notes=[f"Métadonnées : {', '.join(f'{k}={v}' for k, v in info.metadata.items())}"] if info.metadata else [],
        personal=conv.personal,
    )


def manual_proposal(info: FileInfo, ctx: ProposeContext, reason: str) -> Proposal:
    """Proposition vide marquée « à traiter manuellement » (échec de l'IA)."""
    stem, _ = split_extension(info.name)
    return Proposal(
        file_id=info.file_id, source_path=info.path, target_folder="", new_name=info.name,
        fields=NameFields(description=stem), confidence=0.0, reasoning=f"À traiter manuellement : {reason}",
        warnings=[reason], prompt_version=prompt_version(ctx.convention.personal), model=ctx.llm.model, manual=True,
    )


def _existing_names(folder: Path) -> set[str]:
    try:
        return {e.name for e in os.scandir(folder)}
    except OSError:
        return set()


def _make_fields(resp: LLMProposal, folder: str, info: FileInfo, conv: Convention, warnings: list[str]) -> NameFields:
    from_folder = fields_from_folder(folder, conv) if folder else {}
    client_text = _real(resp.client)
    client = conv.client_by_code(client_text)
    if client_text and not client:
        warnings.append(f"Client inconnu : « {client_text} » n'est pas dans la liste des clients.")
    category = conv.find_category(_real(resp.category))
    description = (_real(resp.description) or "").strip() or split_extension(info.name)[0]
    return NameFields(
        date=_parse_date(_real(resp.date)),
        client=from_folder.get("client") or (client.code if client else None),
        project_code=from_folder.get("project_code") or _real(resp.project_code),
        project_name=from_folder.get("project_name") or _real(resp.project_name),
        category=from_folder.get("category") or category,
        description=description,
        version=extract_version(info.name),
    )


MAX_CATEGORY_LENGTH = 30


def _existing_child(parent: Path, name: str, naming) -> str:
    """Nom d'un sous-dossier : l'existant s'il correspond (casse, accents), sinon un nom propre à créer."""
    wanted = clean_segment(name, naming).replace(naming.separator, naming.word_separator).casefold()
    try:
        for entry in os.scandir(parent):
            if entry.is_dir() and (entry.name.casefold() == name.casefold() or
                                   clean_segment(entry.name, naming).replace(naming.separator,
                                                                             naming.word_separator).casefold() == wanted):
                return entry.name
    except OSError:
        pass
    cleaned = clean_segment(name, naming).replace(naming.separator, naming.word_separator)
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def personal_folder(folder: str, category: str | None, new_category: str | None, conv: Convention, root: Path) -> str:
    """Chemin du mode personnel : la catégorie (existante ou nouvelle) puis au plus `max_depth - 1` sous-dossiers.

    Les dossiers existants gardent leur nom exact ; un chemin qui ne commence pas par la catégorie n'en garde que
    celle-ci."""
    parts = [p for p in folder.split("/") if p] if folder else []
    head = new_category or (conv.find_category(parts[0]) if parts else None) or category
    if not head:
        return ""
    head = conv.find_category(head) or head
    same_head = bool(parts) and (conv.find_category(parts[0]) == head or
                                 (new_category is not None and parts[0].casefold() == new_category.casefold()))
    result, parent = [head], root / head
    for part in (parts[1:] if same_head else [])[: conv.structure.max_depth - 1]:
        if is_placeholder(part) or part.startswith((".", "_")):
            break
        name = _existing_child(parent, part, conv.naming)
        if not name or len(name) > MAX_CATEGORY_LENGTH * 2:
            break
        result.append(name)
        parent = parent / name
    return "/".join(result)


def new_category_for(resp: LLMProposal, conv: Convention) -> str | None:
    """Mode personnel : catégorie proposée par l'IA et absente de la liste -> nom de la catégorie à créer."""
    name = _real(resp.category)
    if not conv.personal or not name or conv.find_category(name):
        return None
    code = clean_segment(name.replace("/", " "), conv.naming).replace(conv.naming.separator, conv.naming.word_separator)
    if not code or is_placeholder(code) or len(code) > MAX_CATEGORY_LENGTH or code.startswith("_"):
        return None
    return code[:1].upper() + code[1:]


def finalize(info: FileInfo, resp: LLMProposal, ctx: ProposeContext) -> Proposal:
    """Valide la réponse de l'IA et construit le nom par le code."""
    conv, root = ctx.convention, Path(ctx.root)
    warnings: list[str] = []
    folder = normalize_rel(resp.target_folder)
    if folder is None:
        warnings.append("Dossier proposé hors de la racine : ignoré.")
        folder = ""
    if folder and (has_placeholder(folder) or folder.split("/")[0].casefold() == STAGING_DIRNAME.casefold()):
        folder = ""  # « null/CV/04_Livrables » (client inconnu écrit en toutes lettres) ou dossier interne _TriBin
    fields = _make_fields(resp, folder, info, conv, warnings)
    new_category = new_category_for(resp, conv)
    if conv.personal and conv.structure.max_depth:  # catégorie puis sous-dossiers choisis par l'IA (N niveaux)
        folder = personal_folder(folder, fields.category, new_category, conv, root)
        fields.category = folder.split("/")[0] if folder else fields.category
    elif new_category:  # mode personnel à gabarit fixe : catégorie à créer, chemin selon le gabarit
        fields.category = new_category
        folder = folder_from_fields(fields, conv, fallback_date=info.modified.date())
    if not folder:
        folder = folder_from_fields(fields, conv, fallback_date=info.modified.date())
    if not folder or has_placeholder(folder):
        return manual_proposal(info, ctx, "l'IA n'a pas trouvé de dossier valable (client ou projet inconnu) : "
                                          "choisissez-le avec « Changer… ».")
    abs_folder = root / folder
    if not is_within(abs_folder, root):
        return manual_proposal(info, ctx, "le dossier proposé sort de la racine.")
    if ExclusionMatcher(conv.excluded_paths).matches_rel(folder):
        return manual_proposal(info, ctx, "le dossier proposé est dans une zone exclue.")
    confidence = max(0.0, min(1.0, float(resp.confidence)))
    folder_is_new = not abs_folder.is_dir()
    if folder_is_new and new_category:
        warnings.append(f"Nouvelle catégorie « {new_category} » : le dossier {folder} sera créé.")
    elif folder_is_new:
        warnings.append(f"Création de dossier : {folder}")
        if not matches_template(folder, conv) and not personal_folder_ok(folder, conv):
            warnings.append("Le dossier proposé ne suit pas le gabarit de la convention.")
            confidence = min(confidence, 0.5)
    name, path_warnings = fit_to_path(fields, conv.naming, info.extension, abs_folder, fallback_date=info.modified)
    warnings += path_warnings
    existing = _existing_names(abs_folder)
    if Path(info.path).parent == abs_folder:
        existing.discard(info.name)
    final_name = unique_name(name, existing)
    if final_name != name:
        warnings.append(f"Un fichier « {name} » existe déjà : suffixe ajouté.")
    alternatives = []
    seen = {folder.casefold()}
    for alt in resp.alternatives:
        alt_folder = normalize_rel(alt.target_folder)
        if (not alt_folder or alt_folder.casefold() in seen or has_placeholder(alt_folder)
                or ExclusionMatcher(conv.excluded_paths).matches_rel(alt_folder)):
            continue  # alternative vide, avec « null », identique au premier choix ou en zone exclue
        seen.add(alt_folder.casefold())
        if len(alternatives) == 2:
            break
        alt_fields = fields.model_copy(update={
            **fields_from_folder(alt_folder, conv),
            "description": clean_segment(alt.description, conv.naming) or fields.description,
        })
        alt_fields.category = alt_fields.category if alt_fields.category in conv.category_codes() else fields.category
        alt_name = build_name(alt_fields, conv.naming, info.extension, info.modified)
        alternatives.append(Alternative(target_folder=alt_folder, new_name=alt_name, reasoning=alt.reasoning))
    if alternatives and confidence > ALTERNATIVE_CONFIDENCE_CAP:
        # Règle du prompt appliquée par le code : si l'IA envisage un autre dossier, elle hésite -> « à vérifier ».
        confidence = ALTERNATIVE_CONFIDENCE_CAP
        warnings.append(f"L'IA hésite avec : {alternatives[0].target_folder}")
    return Proposal(
        file_id=info.file_id, source_path=info.path, target_folder=folder, folder_is_new=folder_is_new,
        new_name=final_name, fields=fields, confidence=confidence, reasoning=resp.reasoning.strip(),
        alternatives=alternatives, warnings=warnings, prompt_version=prompt_version(conv.personal), model=ctx.llm.model,
        new_category=new_category,
    )


def propose(info: FileInfo, ctx: ProposeContext) -> Proposal:
    """Produit une proposition pour un fichier ; ne lève pas d'exception (échec -> « à traiter manuellement »)."""
    started = time.monotonic()
    hint = ctx.client_detector(info) if ctx.client_detector else None
    candidates = ctx.candidates(info, hint)
    examples = ctx.examples_provider(info, hint) if ctx.examples_provider else []
    try:
        similar = ctx.similar_provider(info) if ctx.similar_provider else []
    except Exception:  # signal facultatif : jamais bloquant
        log.exception("similar files lookup failed for %s", info.path)
        similar = []
    known = {c.rel.casefold() for c in candidates}
    candidates = [*candidates, *(Candidate(s.folder, "contient des fichiers du même modèle de nom")
                                 for s in similar if s.folder.casefold() not in known)]
    data = build_prompt_data(info, ctx, hint, candidates, examples, similar)
    try:
        resp = ctx.llm.complete_json(system_prompt(ctx.convention.personal, ctx.convention.structure.max_depth or 1),
                                     build_user_prompt(data), LLMProposal,
                                     images=info.images[:1] or None)
        proposal = finalize(info, resp, ctx)
    except LLMError as exc:
        proposal = manual_proposal(info, ctx, str(exc))
    except Exception as exc:  # jamais de plantage : on journalise et on rend la main à l'utilisateur
        log.exception("propose failed for %s", info.path)
        proposal = manual_proposal(info, ctx, f"erreur inattendue ({type(exc).__name__}).")
    if ctx.version_detector and not proposal.manual:
        try:
            ctx.version_detector(info, proposal, ctx)
        except Exception:
            log.exception("version detection failed for %s", info.path)
    proposal.client_hint, proposal.excerpt = hint, info.text[:300]
    proposal.cost_usd = getattr(getattr(ctx.llm, "last_usage", None), "cost_usd", 0.0)
    proposal.duration_s = round(time.monotonic() - started, 2)
    return proposal
