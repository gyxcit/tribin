"""Moteur de proposition : fichier -> Proposal (section 6.3)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath

from tribin.config import STAGING_DIRNAME, is_within
from tribin.convention.loader import Convention
from tribin.convention.naming import build_name, clean_segment, extract_version, fit_to_path, split_extension, unique_name
from tribin.convention.structure import personal_folder_ok, fields_from_folder, folder_from_fields, matches_template
from tribin.engine.candidates import Candidate, phase1_candidates
from tribin.engine.prompts import DEFAULT_PROMPT_STYLE, PromptData, build_prompts, human_size, prompt_version
from tribin.engine.similar import SimilarFolder
from tribin.engine.tools import Tool, ToolSession, default_tools
from tribin.extract import MAX_TEXT
from tribin.fs.filters import ExclusionMatcher
from tribin.llm.base import LLMError, LLMProvider
from tribin.models import Alternative, FileInfo, LLMProposal, NameFields, Proposal

log = logging.getLogger(__name__)

MAX_CLIENTS_IN_PROMPT = 30
# Photos, captures d'écran et vidéos : la date du fichier (ou de prise de vue) est celle du document.
CAPTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".bmp", ".tif", ".tiff",
                      ".mp4", ".mov", ".avi", ".mkv"}
NO_DATE_WARNING = "Date du document introuvable : nom proposé sans date."
# Barème du skill : « 0.55 à 0.74 : deux dossiers se défendent vraiment ». Une alternative retenue plafonne donc la
# confiance affichée : un « 95 % · Sûr » accompagné d'une demande de vérification n'a pas de sens pour l'utilisateur.
HESITATION_MAX_CONFIDENCE = 0.74


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
    tools: list[Tool] | None = None  # outils de l'IA (engine/tools.py) ; None : ceux par défaut, lus sur le disque
    tree: list[str] = field(default_factory=list)  # dernier recours (skill § 2.4) : arborescence dans le prompt, vide par défaut
    create_folders: bool = True  # autorisation (Réglages › Autorisations) : l'IA peut proposer de nouveaux dossiers
    prompt_style: str = DEFAULT_PROMPT_STYLE  # « v2 » (skill de triage) ou « p7 » (ancien prompt, comparaison)
    _phase1_cache: list[Candidate] | None = None

    def tool_set(self) -> list[Tool]:
        if self.tools is None:
            self.tools = default_tools(Path(self.root), None, self.convention.excluded_paths)
        return self.tools

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


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%Y%m%d", "%Y-%m", "%m/%Y")
MAX_FUTURE_DAYS = 366


def _parse_date(value: str | None, today: date | None = None) -> date | None:
    """Date écrite par l'IA : ISO d'abord, puis les formats courants (12/10/2026, 2026-10, 10/2026 : premier du
    mois). Une date avant 1900 ou à plus d'un an dans le futur est rejetée : plutôt pas de date qu'une fausse."""
    if not value:
        return None
    text = str(value).strip().strip("\"'")
    parsed = None
    for candidate in (text, text[:10], text[:7]):
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt).date()
                break
            except ValueError:
                continue
        if parsed:
            break
    if parsed is None:
        return None
    today = today or date.today()
    if parsed.year < 1900 or parsed > today + timedelta(days=MAX_FUTURE_DAYS):
        return None
    return parsed


def date_fallback(document_date_source: str | None, info: FileInfo) -> datetime | date | None:
    """Date mise dans le nom quand l'IA n'en a pas lu dans le document.

    Photos, captures et vidéos : la date de prise de vue (EXIF) ou celle du fichier, qui est bien celle du document.
    Ensuite la date de création écrite dans le document lui-même (propriétés PDF, Word, Excel, PowerPoint) : une
    propriété du document, pas du fichier. Réponse de l'ancien prompt (source inconnue) : date du fichier, comme
    avant. Sinon aucune : un document de 2024 téléchargé aujourd'hui ne doit pas s'appeler 2026-…"""
    if info.extension in CAPTURE_EXTENSIONS:
        taken = info.metadata.get("exif_DateTimeOriginal") or info.metadata.get("exif_DateTime") or ""
        return _parse_date(taken[:10].replace(":", "-")) or info.modified
    created = _parse_date(info.metadata.get("date_creation_document"))
    if created:
        return created
    if document_date_source is None:
        return info.modified
    return None


def _clients_text(convention: Convention) -> str:
    """Liste des clients, stable d'un fichier à l'autre (préfixe mis en cache) : les 30 premiers si elle est longue ;
    le client détecté est rappelé dans le message du fichier."""
    clients = sorted(convention.clients, key=lambda c: c.code)[:MAX_CLIENTS_IN_PROMPT]
    return "; ".join(f"{c.code} : {c.name}" + (f" ({', '.join(c.aliases)})" if c.aliases else "") for c in clients)


def build_prompt_data(info: FileInfo, ctx: ProposeContext, hint: str | None, candidates: list[Candidate],
                      examples: list[str], similar: list[SimilarFolder] | None = None,
                      together: list[str] | None = None) -> PromptData:
    conv = ctx.convention
    client = conv.client_by_code(hint)
    return PromptData(
        personal=conv.personal,
        structure_template=conv.structure.template,
        project_format=conv.structure.project_format,
        categories_with_descriptions="; ".join(f"{c.code} ({c.description})" for c in conv.structure.categories),
        clients_list=_clients_text(conv),
        naming_template=conv.naming.template,
        profile=ctx.profile,
        learned_rules=ctx.rules_provider() if ctx.rules_provider else ctx.learned_rules,
        tree=ctx.tree,
        depth=conv.structure.max_depth or 1,
        create_folders=ctx.create_folders,
        original_name=info.name,
        extension=info.extension,
        mime=info.mime,
        size_human=human_size(info.size),
        created=info.created.strftime("%Y-%m-%d"),
        modified=info.modified.strftime("%Y-%m-%d"),
        origin_folder=info.origin_folder,
        extracted_text=info.text,
        text_truncated=len(info.text) >= MAX_TEXT,
        metadata=", ".join(f"{k}={v}" for k, v in info.metadata.items()),
        extraction_error=info.extraction_error or "",
        candidate_folders=[c.render() for c in candidates],
        project_folders=ctx.project_folders,
        correction_examples=examples,
        similar_files=[s.render() for s in similar or []],
        dropped_together=together or [],
        client_hint=f"{client.code} ({client.name})" if client and client.name else (hint or ""),
        has_image=bool(info.images),
    )


def manual_proposal(info: FileInfo, ctx: ProposeContext, reason: str) -> Proposal:
    """Proposition vide marquée « à traiter manuellement » (échec de l'IA)."""
    stem, _ = split_extension(info.name)
    return Proposal(
        file_id=info.file_id, source_path=info.path, target_folder="", new_name=info.name,
        fields=NameFields(description=stem), confidence=0.0, reasoning=f"À traiter manuellement : {reason}",
        warnings=[reason], prompt_version=prompt_version(ctx.convention.personal, ctx.prompt_style),
        model=ctx.llm.model, manual=True,
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
    category = from_folder.get("category") or conv.find_category(_real(resp.category))
    description = (_real(resp.description) or "").strip() or split_extension(info.name)[0]
    # Un nombre seul en fin de nom (« visuel_3 ») n'est une version que dans les catégories versionnées :
    # « Facture n° 5 », « Chapitre 3 », « CV 2 » n'en sont pas.
    versioned = bool(category) and category in conv.naming.versioned_categories
    return NameFields(
        date=_parse_date(_real(resp.date)),
        client=from_folder.get("client") or (client.code if client else None),
        project_code=from_folder.get("project_code") or _real(resp.project_code),
        project_name=from_folder.get("project_name") or _real(resp.project_name),
        category=category,
        description=description,
        version=extract_version(info.name, bare_number=versioned),
    )


MAX_CATEGORY_LENGTH = 30


def _existing_dir(parent: Path, name: str, naming) -> str | None:
    """Nom exact du sous-dossier existant qui correspond à `name` (casse, accents), sinon None."""
    wanted = clean_segment(name, naming).replace(naming.separator, naming.word_separator).casefold()
    try:
        for entry in os.scandir(parent):
            if entry.is_dir() and not entry.name.startswith((".", "_")) and (
                    entry.name.casefold() == name.casefold() or
                    clean_segment(entry.name, naming).replace(naming.separator,
                                                              naming.word_separator).casefold() == wanted):
                return entry.name
    except OSError:
        pass
    return None


def _existing_child(parent: Path, name: str, naming) -> str:
    """Nom d'un sous-dossier : l'existant s'il correspond (casse, accents), sinon un nom propre à créer."""
    existing = _existing_dir(parent, name, naming)
    if existing:
        return existing
    cleaned = clean_segment(name, naming).replace(naming.separator, naming.word_separator)
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def canonical_folder(folder: str, conv: Convention, root: Path) -> str:
    """Mode Professionnel : chaque segment prend le nom exact du dossier existant (casse, accents) ; à défaut, le code
    du client ou de la catégorie tel qu'il est écrit dans la convention. « acme/2026/…/06_admin » devient
    « ACME/2026/…/06_Admin » : la catégorie est reconnue et aucun doublon de dossier n'est créé à côté."""
    parts = [p for p in folder.split("/") if p]
    levels = conv.structure.template.split("/")
    out: list[str] = []
    parent = Path(root)
    for i, part in enumerate(parts):
        existing = _existing_dir(parent, part, conv.naming) if parent.is_dir() else None
        if existing:
            name = existing
        else:
            level = levels[i] if i < len(levels) else ""
            if level == "{client}":
                client = conv.client_by_code(part)
                name = client.code if client else part
            elif level == "{category}":
                name = conv.find_category(part) or part
            else:
                name = part
        out.append(name)
        parent = parent / name
    return "/".join(out)


def user_folder(folder: str, conv: Convention, root: Path) -> str | None:
    """Mode personnel : dossier de premier niveau créé par l'utilisateur hors des catégories (« startup »), s'il
    existe déjà : une destination comme une autre, jamais transformée en nouvelle catégorie."""
    parts = [p for p in folder.split("/") if p] if folder else []
    if not parts or conv.find_category(parts[0]):
        return None
    return _existing_dir(root, parts[0], conv.naming)


def personal_folder(folder: str, category: str | None, new_category: str | None, conv: Convention, root: Path) -> str:
    """Chemin du mode personnel : le dossier de l'utilisateur déjà présent, sinon la catégorie en tête du chemin
    proposé, sinon la catégorie à créer, sinon le champ `category` ; puis au plus `max_depth - 1` sous-dossiers.

    Les dossiers existants gardent leur nom exact ; un chemin qui ne commence pas par la catégorie n'en garde que
    celle-ci."""
    parts = [p for p in folder.split("/") if p] if folder else []
    mine = user_folder(folder, conv, root)
    in_path = conv.find_category(parts[0]) if parts else None
    head = mine or in_path or new_category or conv.find_category(category) or category
    if not head:
        return ""
    same_head = bool(parts) and (bool(mine) or in_path == head or
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


def new_category_for(resp: LLMProposal, conv: Convention, folder: str = "") -> str | None:
    """Mode personnel : catégorie proposée par l'IA et absente de la liste -> nom de la catégorie à créer.

    Un chemin qui commence par une catégorie existante prime sur le champ `category` (« Design » +
    « Photos/Logos » : rien à créer). « Design/Sarah-Mbossa » comme catégorie donne « Design ». Sans catégorie, le
    premier segment d'un chemin neuf en tient lieu (« Design/Sarah » -> « Design »)."""
    if not conv.personal:
        return None
    parts = [p for p in (folder or "").replace("\\", "/").split("/") if p]
    if parts and conv.find_category(parts[0]):
        return None
    name = _real(resp.category)
    if name:
        name = name.replace("\\", "/").split("/")[0].strip()
    if not name and parts:
        name = parts[0]
    if not name or is_placeholder(name) or conv.find_category(name):
        return None
    code = clean_segment(name, conv.naming).replace(conv.naming.separator, conv.naming.word_separator)
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
    if folder and not conv.personal:
        folder = canonical_folder(folder, conv, root)  # « acme/…/06_admin » -> « ACME/…/06_Admin »
    fields = _make_fields(resp, folder, info, conv, warnings)
    new_category = new_category_for(resp, conv, folder)
    if conv.personal and user_folder(folder, conv, root):
        new_category = None  # « startup » existe déjà : pas une catégorie à créer
    if conv.personal and conv.structure.max_depth:  # catégorie puis sous-dossiers choisis par l'IA (N niveaux)
        folder = personal_folder(folder, fields.category, new_category, conv, root)
        fields.category = folder.split("/")[0] if folder else fields.category
    elif new_category:  # mode personnel à gabarit fixe : catégorie à créer, chemin selon le gabarit
        fields.category = new_category
        folder = folder_from_fields(fields, conv, fallback_date=info.modified.date())
    if not folder:
        folder = folder_from_fields(fields, conv, fallback_date=info.modified.date())
    if not folder or has_placeholder(folder):
        why = "" if conv.personal else " (client ou projet inconnu)"
        asked = _real(resp.target_folder)
        said = f" (elle proposait « {asked} »)" if asked else ""  # pour comprendre le refus, sans relancer l'analyse
        return manual_proposal(info, ctx, f"l'IA n'a pas trouvé de dossier valable{why}{said} : choisissez-le avec "
                                          "« Changer… ».")
    abs_folder = root / folder
    if not is_within(abs_folder, root):
        return manual_proposal(info, ctx, "le dossier proposé sort de la racine.")
    if ExclusionMatcher(conv.excluded_paths).matches_rel(folder):
        return manual_proposal(info, ctx, "le dossier proposé est dans une zone exclue.")
    confidence = max(0.0, min(1.0, float(resp.confidence)))
    folder_is_new = not abs_folder.is_dir()
    ask = "" if ctx.create_folders else " (avec votre accord)"  # Réglages › Autorisations
    if folder_is_new and new_category:
        warnings.append(f"Nouvelle catégorie « {new_category} » : le dossier {folder} sera créé{ask}.")
    elif folder_is_new:
        warnings.append(f"Création de dossier : {folder}{ask}")
        if not matches_template(folder, conv) and not personal_folder_ok(folder, conv, root):
            warnings.append("Le dossier proposé ne suit pas le gabarit de la convention.")
            confidence = min(confidence, 0.5)
    fallback = date_fallback(resp.document_date_source, info)
    if fields.date is None and fallback is None and "{date}" in conv.naming.template:
        warnings.append(NO_DATE_WARNING)  # plutôt pas de date qu'une fausse (celle du fichier)
    name, path_warnings = fit_to_path(fields, conv.naming, info.extension, abs_folder, fallback_date=fallback)
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
        if alt_folder and not conv.personal:
            alt_folder = canonical_folder(alt_folder, conv, root)
        if (not alt_folder or alt_folder.casefold() in seen or has_placeholder(alt_folder)
                or ExclusionMatcher(conv.excluded_paths).matches_rel(alt_folder)):
            continue  # alternative vide, avec « null », identique au premier choix ou en zone exclue
        seen.add(alt_folder.casefold())
        if len(alternatives) == 2:
            break
        alt_fields = fields.model_copy(update={
            **fields_from_folder(alt_folder, conv),
            "description": clean_segment(_real(alt.description) or "", conv.naming) or fields.description,
        })
        alt_fields.category = alt_fields.category if alt_fields.category in conv.category_codes() else fields.category
        alt_name = build_name(alt_fields, conv.naming, info.extension, fallback)
        alternatives.append(Alternative(target_folder=alt_folder, new_name=alt_name, reasoning=alt.reasoning))
    if alternatives:
        # L'IA envisage un autre dossier : « à vérifier » (Proposal.hesitant), et la confiance affichée dit la même
        # chose (au plus 0,74, comme le barème le demande) : une seule confiance, celle sur la destination.
        warnings.append(f"L'IA hésite avec : {alternatives[0].target_folder}")
        confidence = min(confidence, HESITATION_MAX_CONFIDENCE)
    return Proposal(
        file_id=info.file_id, source_path=info.path, target_folder=folder, folder_is_new=folder_is_new,
        new_name=final_name, fields=fields, confidence=confidence, reasoning=resp.reasoning.strip(),
        alternatives=alternatives, warnings=warnings, prompt_version=prompt_version(conv.personal, ctx.prompt_style),
        model=ctx.llm.model, new_category=new_category,
        document_kind=_real(resp.document_kind), subject=_real(resp.subject),
        document_date_source=_real(resp.document_date_source),
        evidence=[e.strip() for e in resp.evidence if e and e.strip()][:6],
    )


def propose(info: FileInfo, ctx: ProposeContext, together: list[str] | None = None) -> Proposal:
    """Produit une proposition pour un fichier ; ne lève pas d'exception (échec -> « à traiter manuellement »).

    `together` : fichiers du même lot déjà analysés et qui lui ressemblent (« « Logos-1.png » → Design/Sarah ») :
    l'IA range ensemble ce qui va ensemble."""
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
    candidates = [*candidates, *(Candidate(s.folder, s.reason) for s in similar if s.folder.casefold() not in known)]
    data = build_prompt_data(info, ctx, hint, candidates, examples, similar, together)
    system, user = build_prompts(data, ctx.prompt_style)
    # Budget d'appels d'outil propre à ce fichier (l'ancien prompt p7 ne connaît pas les outils)
    session = ToolSession(ctx.tool_set()) if ctx.prompt_style != "p7" else None
    try:
        resp = ctx.llm.complete_json(system, user, LLMProposal, images=info.images[:1] or None,
                                     tools=session.declarations if session else None, call_tool=session)
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
    if session is not None:
        proposal.tool_calls = list(session.calls)
    usage = getattr(ctx.llm, "last_usage", None)
    if usage is not None:
        proposal.cost_usd = getattr(usage, "cost_usd", 0.0)
        proposal.input_tokens = getattr(usage, "input_tokens", 0)
        proposal.output_tokens = getattr(usage, "output_tokens", 0)
        proposal.cached_input_tokens = getattr(usage, "cached_input_tokens", 0)
    proposal.duration_s = round(time.monotonic() - started, 2)
    return proposal
