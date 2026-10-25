"""Ancien prompt (p7 / p8-perso), conservé pour la comparaison avec le skill v2 (`tribin eval --prompt p7`).

Tout le contexte est dans le message utilisateur ; le `system` ne contient que les règles."""

from __future__ import annotations

from tribin.engine.prompts import PromptData

PROMPT_VERSION = "p7"
PERSONAL_PROMPT_VERSION = "p8-perso"

SYSTEM_PROMPT = """Tu es l'assistant de rangement de fichiers d'une équipe. Ta mission : proposer
le dossier où ranger un fichier et les éléments de son nouveau nom, en respectant
STRICTEMENT la convention d'équipe fournie.

Règles :
- Choisis de préférence un dossier existant parmi les candidats fournis.
- Si aucun candidat ne convient, construis le chemin avec un projet de la liste
  « Projets existants » et une catégorie de la convention.
{work_creation}
- Si la section « Fichiers déjà rangés qui ressemblent à celui-ci » montre des
  fichiers « au nom du même modèle », l'utilisateur range déjà ce type de fichier
  dans ce dossier : c'est la destination la plus probable, MÊME s'il ne suit pas
  le gabarit (dossier personnel, RH, banque…). Choisis-le avec confidence 0.85 à
  0.95, sauf si le contenu du fichier le contredit ; client et projet peuvent alors
  rester null. Des fichiers qui partagent seulement un mot du nom sont un indice,
  à confirmer par le contenu.
- Si la section « Déposés en même temps » montre des fichiers du même projet, de
  la même personne ou de la même série, range celui-ci au MÊME endroit qu'eux.
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
  alternatives : seulement si tu hésites vraiment entre deux destinations (un
  humain tranchera) ; une piste nettement moins adaptée n'en est pas une : laisse
  alors la liste vide. Donne ta vraie confiance pour la proposition principale.
- Réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte autour."""

PERSONAL_RULES = """

Mode personnel (papiers et fichiers d'une personne, pas d'une agence) :
- Il n'y a ni client ni projet : client, project_code et project_name = null.
- Un dossier existant n'est le bon que s'il parle VRAIMENT du même sujet : même
  projet, même personne, même organisme ou même type de document, ce que montrent
  le contenu du fichier, un mot distinctif commun (« Stagio ») ou une correction
  passée. Un thème vague (« projet », « personnel », « création ») ne suffit pas.
  Alors, un dossier créé par l'utilisateur hors de la liste (« startup ») compte
  autant qu'une catégorie : range-y le fichier.
- La catégorie doit correspondre à la NATURE du document : des logos, maquettes ou
  visuels créés ne sont pas des « Photos » (photos et vidéos personnelles) ; un
  travail réalisé pour quelqu'un n'est pas des « Etudes ».
{personal_creation}
- target_folder : la catégorie (ou le dossier existant choisi), puis AU PLUS {subs}
  niveau(x) de sous-dossiers ({depth} niveaux au total). Réutilise d'abord les
  sous-dossiers existants (liste des candidats). Pas de dossier par année, sauf
  s'il existe déjà pour ce type de document.
- description : 2 à 5 mots qui gardent le nom propre utile (personne, projet,
  organisme : « Logos Sarah Mbossa », « Facture Stagio »), sans la date.
- confidence : 0.85 à 0.95 si la nature du document correspond clairement à un
  dossier (existant ou créé) ; 0.6 à 0.8 si deux dossiers sont plausibles ;
  moins de 0.6 si tu ne comprends pas le document."""

# Autorisation « Créer des dossiers » (Réglages › Autorisations)
WORK_CREATE = """- Ne propose un nouveau dossier que s'il suit le gabarit de structure de la
  convention ; indique alors folder_is_new = true."""
WORK_NO_CREATE = """- Ne propose AUCUN nouveau dossier (l'utilisateur ne l'autorise pas) : choisis
  parmi les candidats et les projets existants."""
PERSONAL_CREATE = """- Si aucun dossier existant ne correspond vraiment, CRÉE un dossier dédié plutôt
  que de forcer un dossier approximatif : une catégorie quand la nature du document
  n'en a pas (category = nom court en français, 1 ou 2 mots, sans accent :
  « Design », « Voyages », « Animaux »), puis un sous-dossier au nom du projet ou de
  la personne quand plusieurs fichiers le concernent (« Design/Sarah-Mbossa »).
  Indique alors folder_is_new = true. Crée aussi un sous-dossier quand il regroupe
  un type de document qui reviendra (« Etudes/Certifications/Universite »)."""
PERSONAL_NO_CREATE = """- Ne crée AUCUN dossier (l'utilisateur ne l'autorise pas) : ni catégorie ni sous-
  dossier. Choisis le dossier existant le plus adapté (candidats). Si aucun ne
  convient, target_folder = "" et confidence < 0.3 : l'utilisateur choisira."""


def system_prompt(personal: bool, depth: int = 3, create_folders: bool = True) -> str:
    base = SYSTEM_PROMPT.replace("{work_creation}", WORK_CREATE if create_folders else WORK_NO_CREATE)
    if not personal:
        return base
    rules = PERSONAL_RULES.replace("{personal_creation}", PERSONAL_CREATE if create_folders else PERSONAL_NO_CREATE)
    return base + rules.replace("{subs}", str(max(0, depth - 1))).replace("{depth}", str(depth))


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
    notes = [f"Métadonnées : {d.metadata}"] if d.metadata else []
    if d.has_image:
        notes.append(IMAGE_NOTE)
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
        _section("Déposés en même temps, déjà analysés (fichier → dossier proposé)", _bullets(d.dropped_together)),
        _section("Exemples de corrections passées (fichier d'origine → choix final)", _bullets(d.correction_examples)),
        _section("Indice", f"Client détecté automatiquement (peut être faux) : {d.client_hint}" if d.client_hint else ""),
        _section("Fichier à ranger", file_block),
        _section("Format de réponse attendu", RESPONSE_FORMAT),
    ]
    return "\n".join(p for p in parts if p)
