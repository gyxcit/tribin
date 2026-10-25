"""Gabarits de prompt du moteur de proposition (section 8). Incrémenter PROMPT_VERSION à chaque modification."""

from __future__ import annotations

from dataclasses import dataclass, field

PROMPT_VERSION = "p6"
PERSONAL_PROMPT_VERSION = "p7-perso"

SYSTEM_PROMPT = """Tu es l'assistant de rangement de fichiers d'une équipe. Ta mission : proposer
le dossier où ranger un fichier et les éléments de son nouveau nom, en respectant
STRICTEMENT la convention d'équipe fournie.

Règles :
- Choisis de préférence un dossier existant parmi les candidats fournis.
- Si aucun candidat ne convient, construis le chemin avec un projet de la liste
  « Projets existants » et une catégorie de la convention.
- Ne propose un nouveau dossier que s'il suit le gabarit de structure de la
  convention ; indique alors folder_is_new = true.
- Si la section « Fichiers du même modèle de nom déjà rangés » est présente,
  l'utilisateur range déjà ce type de fichier dans ce dossier : c'est la
  destination la plus probable, MÊME s'il ne suit pas le gabarit (dossier
  personnel, RH, banque…). Choisis-le avec confidence 0.85 à 0.95, sauf si le
  contenu du fichier le contredit ; client et projet peuvent alors rester null.
- Le client doit être un code de la liste des clients. S'il est inconnu, mets
  client = null et explique-le dans reasoning.
- target_folder ne contient JAMAIS « null », « None », « inconnu » ni un champ du
  gabarit ({client}…). Si aucun dossier ne convient (client inconnu, fichier
  personnel ou hors des projets), mets target_folder = "" et confidence < 0.3 :
  un humain choisira.
- N'invente aucune information absente du fichier. Si la date du document
  n'est pas identifiable, mets date = null.
- description : 2 à 5 mots, précis et utiles pour retrouver le fichier
  (ex. "Devis impression affiches"), sans répéter le client, la date ni la version.
- Les exemples de corrections montrent les préférences de cet utilisateur :
  suis-les, sauf s'ils contredisent la convention d'équipe.
- confidence : applique ce barème (une erreur coûte cher : une note basse fait
  vérifier le fichier par un humain) :
  0.9 à 1 : le contenu nomme le client, le projet ET la nature du document, et
            cette nature correspond sans ambiguïté à une seule catégorie
            (ex. « FACTURE … projet 2026-042 » → Admin) ;
  0.7 à 0.85 : client et projet certains, catégorie déduite mais une seule plausible ;
  0.4 à 0.55 : deux catégories ou deux projets sont plausibles, ou le fichier n'a
            pas de texte et tu te fondes sur le nom, la date ou l'image ;
  moins de 0.4 : tu devines.
  Si une autre destination est plausible, indique-la dans alternatives : un humain
  tranchera. Donne quand même ta vraie confiance pour la proposition principale.
- Réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte autour."""

PERSONAL_RULES = """

Mode personnel (papiers et fichiers d'une personne, pas d'une agence) :
- Il n'y a ni client ni projet : client, project_code et project_name = null.
- Les dossiers existants comptent autant que les catégories, même s'ils ne sont pas
  dans la liste (« startup », « Voyage-Japon » : créés par l'utilisateur). Si un dossier
  contient déjà des fichiers du même sujet, du même projet ou portant le même mot
  distinctif (voir « Fichiers déjà rangés qui ressemblent à celui-ci », le contenu du
  fichier et les corrections passées), range le fichier dans ce dossier plutôt que
  dans une catégorie générale : c'est là que l'utilisateur le cherchera.
- Sinon, choisis la catégorie la plus adaptée dans la liste (le nom du dossier existant
  compte : « salaire » pour un bulletin de paie s'il existe).
- Si AUCUNE catégorie ne convient vraiment, crée-en une : category = nom court
  en français, 1 ou 2 mots, sans accent (ex. « Animaux », « Voyages »). N'en
  crée pas si une catégorie existante convient, même approximativement.
- target_folder : la catégorie, puis AU PLUS {subs} niveau(x) de sous-dossiers ({depth} niveaux au total).
  Réutilise d'abord les sous-dossiers existants (liste des candidats). Crée un sous-
  dossier quand il regroupe un type de document qui reviendra, du plus général au
  plus précis (ex. « Etudes/Certifications/Universite », « Etudes/Attestations/
  Benevolat ») ; sinon range directement dans la catégorie (« Etudes »). Pas de
  dossier par année, sauf s'il existe déjà pour ce type de document.
- confidence : 0.85 à 0.95 si la nature du document correspond clairement à une
  catégorie (existante ou créée) ; 0.6 à 0.8 si deux catégories sont plausibles ;
  moins de 0.6 si tu ne comprends pas le document."""


def system_prompt(personal: bool, depth: int = 3) -> str:
    if not personal:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + PERSONAL_RULES.replace("{subs}", str(max(0, depth - 1))).replace("{depth}", str(depth))


def prompt_version(personal: bool) -> str:
    return PERSONAL_PROMPT_VERSION if personal else PROMPT_VERSION


RESPONSE_FORMAT = """{
  "client": "CODE ou null",
  "project_code": "texte ou null",
  "project_name": "texte ou null",
  "category": "code de catégorie ou null",
  "date": "AAAA-MM-JJ ou null",
  "description": "2 à 5 mots",
  "target_folder": "chemin relatif à la racine",
  "folder_is_new": false,
  "confidence": 0.0,
  "reasoning": "1 à 2 phrases en français",
  "alternatives": [
    {"target_folder": "...", "category": "...", "description": "...", "reasoning": "..."}
  ]
}"""

IMAGE_NOTE = "Une image du fichier est jointe."


@dataclass
class PromptData:
    """Valeurs qui remplissent les blocs {{...}} du prompt."""

    structure_template: str
    project_format: str
    categories_with_descriptions: str
    clients_list: str
    original_name: str
    extension: str
    mime: str
    size_human: str
    created: str
    modified: str
    origin_folder: str
    extracted_text: str = ""
    profile: str = ""
    learned_rules: list[str] = field(default_factory=list)
    candidate_folders: list[str] = field(default_factory=list)
    project_folders: list[str] = field(default_factory=list)
    correction_examples: list[str] = field(default_factory=list)
    similar_files: list[str] = field(default_factory=list)
    client_hint: str = ""
    has_image: bool = False
    extra_notes: list[str] = field(default_factory=list)
    personal: bool = False


def _section(title: str, body: str) -> str:
    return f"## {title}\n{body.strip()}\n" if body and body.strip() else ""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def build_user_prompt(d: PromptData) -> str:
    """Assemble le message utilisateur ; une section vide est omise."""
    if d.personal:
        convention = (f"Mode : personnel (ni client ni projet)\nStructure : {d.structure_template}\n"
                      f"Catégories : {d.categories_with_descriptions}")
    else:
        convention = (f"Structure : {d.structure_template}\nFormat des projets : {d.project_format}\n"
                      f"Catégories : {d.categories_with_descriptions}\nClients (code : nom, alias) : {d.clients_list}")
    file_block = (
        f"Nom d'origine : {d.original_name}\n"
        f"Type : {d.extension or '(sans extension)'} — {d.mime} — {d.size_human}\n"
        f"Dates : créé le {d.created}, modifié le {d.modified}\n"
        f"Dossier d'origine : {d.origin_folder}\n"
        f"Contenu extrait :\n\"\"\"\n{d.extracted_text.strip() or '(aucun texte extrait)'}\n\"\"\""
    )
    notes = [*d.extra_notes, IMAGE_NOTE] if d.has_image else d.extra_notes
    if notes:
        file_block += "\n" + "\n".join(notes)
    parts = [
        _section("Profil de l'utilisateur", d.profile),
        _section("Convention d'équipe", convention),
        _section("Règles apprises de cet utilisateur", _bullets(d.learned_rules)),
        _section("Dossiers candidats (chemin relatif — description)", _bullets(d.candidate_folders)),
        _section("Projets existants", ", ".join(d.project_folders)),
        _section("Fichiers déjà rangés qui ressemblent à celui-ci (même modèle de nom ou même mot distinctif)",
                 _bullets(d.similar_files)),
        _section("Exemples de corrections passées (fichier d'origine → choix final)", _bullets(d.correction_examples)),
        _section("Indice", f"Client détecté automatiquement (peut être faux) : {d.client_hint}" if d.client_hint else ""),
        _section("Fichier à ranger", file_block),
        _section("Format de réponse attendu", RESPONSE_FORMAT),
    ]
    return "\n".join(p for p in parts if p)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go"):
        if value < 1024 or unit == "Go":
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} o"
