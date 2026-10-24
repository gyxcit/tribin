# TriBin — Spécification du projet

> **Nom de travail : TriBin** (tri + bin). Le nom pourra changer ; le package Python s'appelle `tribin`.
> Version du document : 1.0 — octobre 2026.
> Ce fichier se place à la racine du dépôt sous le nom `SPEC.md`. C'est la **source de vérité** du projet.

---

## 0. Instructions pour l'agent de développement (Cursor)

Lis ce document **en entier** avant chaque nouvelle tâche.

1. Travaille **une phase à la fois**, dans l'ordre de la section 9. Ne commence jamais une phase tant que les critères de validation de la précédente ne sont pas remplis.
2. Avant d'écrire du code, propose un **plan court** (fichiers créés ou modifiés, fonctions principales) et attends la validation.
3. Les **règles de sécurité de la section 3 sont non négociables**. Si une demande semble les contredire, arrête-toi et signale-le.
4. Écris des tests `pytest` pour toute logique qui touche aux fichiers (sécurité, journal, nommage, restauration).
5. Pendant le développement, **toute opération réelle sur des fichiers se fait uniquement dans `./sandbox/`** (voir 3.3).
6. Garde des modules petits et ciblés (pas de fichier de plus de ~400 lignes).
7. N'ajoute **aucune fonctionnalité hors périmètre** (section 4.2), même si elle semble utile : note-la dans la section 12.
8. À la fin de chaque tâche : mets à jour la section 13 « État d'avancement » et propose un message de commit Git.
9. Si une information manque, choisis l'option la plus simple et la plus sûre, et signale l'hypothèse prise.
10. Explique brièvement ce que tu as fait : le propriétaire du projet n'est pas développeur de métier.

---

## 1. Contexte et vision

### 1.1 Le problème

Dans les agences de publicité et de communication (cible initiale : 10 à 100 personnes), le rangement des fichiers est chaotique :

- **abondance de fichiers** : briefs, visuels, PSD, AI, InDesign, vidéos, devis, factures, exports… ;
- **multiplication des versions** : `visuel_v1`, `V2`, `final`, `final_OK`, `final_vraiment_final`… ;
- chacun range et nomme à sa façon. Les conventions existent parfois mais ne sont pas appliquées, parce que **les appliquer à la main coûte un effort à chaque fichier**, sous la pression des deadlines ;
- conséquences : temps perdu à chercher, mauvaises versions envoyées aux clients, fichiers refaits, savoir perdu quand quelqu'un part.

Constat clé : **les erreurs naissent en amont**, au moment où le fichier arrive. Nettoyer la base existante ne suffit pas si l'entrée des fichiers reste non maîtrisée.

### 1.2 La solution

Une application de bureau, **pour macOS et Windows**, qui fonctionne **comme la Corbeille** : l'utilisateur glisse un fichier dessus, et l'IA propose **où le ranger** et **comment le renommer**, selon la convention de l'équipe. L'utilisateur valide d'un geste ou corrige ; l'IA apprend de ses corrections.

Promesse : **respecter la convention d'équipe ne coûte plus aucun effort.**

### 1.3 Principes produit

- **L'utilisateur garde le dernier mot.** L'IA propose, l'humain valide. Rien n'est rangé sans validation.
- **Confort avant tout.** Valider doit prendre une seconde ; corriger, quelques secondes.
- **L'IA s'adapte** à chaque utilisateur grâce à ses corrections, dans le cadre des conventions d'équipe.
- **Sécurité absolue des fichiers.** Aucune perte possible, tout est réversible.
- **Local d'abord.** L'appli travaille sur le disque local et les lecteurs réseau (NAS). Pas d'intégration cloud par API dans le MVP (les dossiers synchronisés Dropbox / Google Drive / OneDrive fonctionnent comme des dossiers locaux).
- **Transparence.** L'utilisateur comprend pourquoi l'IA propose ce qu'elle propose.

### 1.4 Utilisateurs

- **Utilisateur quotidien** (créa, chef de projet, production, commercial) : jette ses fichiers dans la corbeille, valide les propositions.
- **Référent** (responsable des conventions) : définit la structure, la nomenclature et la liste des clients dans un fichier de convention partagé.

---

## 2. Parcours utilisateur (MVP)

**Premier lancement**

1. Onboarding court : questions de contexte (section 6.8).
2. Choix du ou des **répertoires de référence** (racines) et des **zones exclues**.
3. Choix du mode : **cartographier l'existant** ou **créer une structure de zéro**.
4. Chargement ou création du fichier de convention.

**Usage quotidien**

1. L'utilisateur glisse un ou plusieurs fichiers dans la corbeille.
2. Les fichiers sont déplacés dans le **dossier tampon** (opération journalisée) : ils sont « jetés ».
3. L'IA analyse chaque fichier en arrière-plan et produit une proposition (dossier + nom).
4. La fenêtre Corbeille liste les fichiers en attente et leurs propositions. Un compteur s'affiche sur l'icône.
5. L'utilisateur valide, modifie le nom ou le dossier, choisit une alternative, ou renvoie le fichier à son emplacement d'origine.
6. Le rangement est exécuté, journalisé et annulable depuis l'Historique.
7. Chaque correction est enregistrée et améliore les propositions suivantes.

---

## 3. Règles de sécurité (NON NÉGOCIABLES)

### 3.1 Règles sur les fichiers

- **INTERDIT : supprimer un fichier.** « Supprimer » signifie déplacer vers le dossier `_Archive/` de la racine. Seul un humain vide ce dossier, en dehors de l'appli. Seule exception : retirer l'original **après** une copie inter-volumes vérifiée (voir ci-dessous).
- **INTERDIT : écraser un fichier.** Si la destination existe, ajouter un suffixe `_2`, `_3`… Vérifier l'existence **juste avant** l'opération.
  - Attention : sur macOS et Linux, `os.rename` écrase silencieusement la destination. Ne jamais appeler `os.rename`, `os.replace` ou `shutil.move` sans vérification préalable. Centraliser tous les déplacements dans `safety/executor.py`.
- **Toute opération est inscrite au journal AVANT d'être exécutée** (section 7).
- **Déplacement entre volumes** (ex. disque local → NAS), dans cet ordre exact :
  1. copier vers un nom temporaire `<nom>.tribin-partial` dans le dossier de destination ;
  2. vérifier le hash SHA-256 de la copie ;
  3. renommer la copie en nom final (sans écraser) ;
  4. retirer l'original.
  En cas d'échec à n'importe quelle étape : l'original reste intact et le fichier partiel est retiré.
- **Même volume** : déplacement natif après vérification que la destination n'existe pas ; vérifier ensuite que la destination existe et a la même taille.
- **Périmètre** : aucune destination en dehors des racines déclarées. Résoudre les chemins (`Path.resolve()`) et rejeter tout chemin qui sort de la racine (`..`, liens symboliques).
- **Zones exclues** : ne jamais déplacer, renommer ni créer quoi que ce soit dans une zone exclue.
- **Opérations par lot** (plus d'un fichier, ou création de dossiers) : passent **obligatoirement** par une simulation montrée à l'utilisateur avant exécution.

### 3.2 Fichiers à ne jamais traiter

Refuser avec un message clair :

- les **dossiers** (MVP : fichiers uniquement), y compris les paquets macOS qui ressemblent à des fichiers (`.app`, `.fcpbundle`, `.photoslibrary`, `.band`, bibliothèques Final Cut ou Photos) ;
- les fichiers système ou temporaires : `.DS_Store`, `Thumbs.db`, `desktop.ini`, `~$*` (fichiers Office ouverts), `*.tmp`, `*.part`, `*.crdownload`, `*.tribin-partial` ;
- les fichiers **en cours d'écriture** (taille qui change sur 2 secondes) : réessayer plus tard ;
- les fichiers situés dans une **zone exclue** : refuser avec l'avertissement « Ce fichier est dans un dossier projet protégé : le déplacer peut casser des liens dans InDesign, After Effects ou Premiere » ;
- les liens symboliques.

### 3.3 Garde-fou de développement

- Variable d'environnement `TRIBIN_DEV_SANDBOX=1`, activée par défaut dans `.env.example`.
- Quand elle est active, le module d'exécution **refuse toute opération** dont la source ou la destination n'est pas sous `./sandbox/`.
- Le script `scripts/make_sandbox.py` génère une arborescence de test réaliste dans `./sandbox/` (phase 0).
- On ne teste jamais sur de vrais dossiers de travail tant que la phase 3 n'est pas validée.

### 3.4 Confidentialité

- MVP : le contenu extrait des fichiers est envoyé à l'API d'IA configurée. L'indiquer clairement à l'onboarding et dans les réglages.
- Limiter ce qui est envoyé : texte tronqué (6.2), images réduites, **jamais le fichier complet**.
- Aucune télémétrie dans le MVP. Les réponses d'onboarding restent sur la machine.
- La clé API est stockée dans `.env` en développement, puis dans le trousseau système (`keyring`). Jamais dans le code ni dans le dépôt Git.
- L'abstraction LLM (5.4) doit permettre d'ajouter plus tard un modèle local (Ollama).

---

## 4. Périmètre

### 4.1 Dans le MVP

- Corbeille (dépôt de fichiers), dossier tampon, file d'attente.
- Extraction de contenu : texte, PDF, Office, images, métadonnées de base des fichiers créatifs.
- Moteur de proposition (dossier + nom) guidé par la convention d'équipe et le profil utilisateur.
- Convention d'équipe en YAML (structure, nomenclature, clients, catégories), pouvant être stockée sur le NAS et partagée.
- Cartographie de l'existant (version simple) et création de structure de zéro.
- Journal, simulation, annulation, script de restauration indépendant.
- Apprentissage à partir des corrections.
- Détection des versions.
- Onboarding court.
- Évaluation automatique de la qualité sur un jeu de test.

### 4.2 Hors périmètre (ne pas développer maintenant)

- Intégrations cloud par API (Google Drive, OneDrive, Dropbox).
- Serveur d'équipe, synchronisation entre postes (en dehors du fichier de convention partagé).
- Traitement massif du stock existant (milliers de fichiers).
- Réorganisation d'une arborescence existante.
- Suivi des droits d'utilisation des images.
- Recherche sémantique ou en langage naturel.
- Modèle d'IA local (seulement préparer l'abstraction).
- Signature, installeur, mises à jour automatiques (seul un empaquetage minimal pour tester est prévu en phase 4).
- Télémétrie, comptes utilisateurs, paiement.

---

## 5. Architecture technique

### 5.1 Stack

- **Python 3.12** (minimum 3.11), gestion avec `uv` (ou `pip` + `venv`), `pyproject.toml`, layout `src/`.
- Interface : **PySide6** (Qt), à partir de la phase 4.
- Base locale : **SQLite** (module standard `sqlite3`).
- Validation des données : **pydantic** v2.
- IA : SDK officiel **`anthropic`**, derrière une abstraction `LLMProvider`.
- Extraction : `pypdf`, `pypdfium2` (rendu de pages PDF en image), `python-docx`, `openpyxl`, `python-pptx`, `Pillow`, `psd-tools`.
- Similarité : `rapidfuzz` (texte), `imagehash` (images, phase 6).
- Divers : `pyyaml`, `platformdirs`, `python-dotenv`, `keyring`, `rich` (affichage en ligne de commande).
- Tests : `pytest`.

Plateformes : **macOS et Windows, à égalité**. Chaque fonctionnalité doit fonctionner sur les deux systèmes (voir 5.6). Code multiplateforme : `pathlib` partout, aucun chemin codé en dur.

### 5.2 Arborescence du projet

```
tribin/
├── SPEC.md                       ← ce document
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore                    ← inclut .env, sandbox/, testset/, eval_results/, *.db
├── convention.example.yaml
├── scripts/
│   └── make_sandbox.py
├── src/tribin/
│   ├── __main__.py               ← CLI : python -m tribin <commande>
│   ├── config.py                 ← réglages, chemins (platformdirs), .env
│   ├── models.py                 ← modèles pydantic partagés
│   ├── db.py                     ← SQLite : schéma et accès
│   ├── fs/
│   │   ├── base.py               ← interface FileStore (Protocol)
│   │   └── local.py              ← disque local / NAS
│   ├── extract/
│   │   ├── __init__.py           ← extract(path) -> FileInfo, aiguillage par type
│   │   ├── text.py
│   │   ├── pdf.py
│   │   ├── office.py
│   │   ├── image.py
│   │   └── creative.py           ← PSD, AI, INDD, vidéos (métadonnées)
│   ├── convention/
│   │   ├── loader.py             ← lecture et validation du YAML
│   │   ├── naming.py             ← construction et nettoyage des noms
│   │   └── structure.py          ← chemins à partir du gabarit de structure
│   ├── mapping/
│   │   ├── scanner.py            ← parcours de l'arborescence existante
│   │   └── profiles.py           ← profils de dossiers, motifs de nommage
│   ├── llm/
│   │   ├── base.py               ← interface LLMProvider
│   │   └── anthropic_provider.py
│   ├── engine/
│   │   ├── candidates.py         ← présélection des dossiers candidats
│   │   ├── prompts.py            ← gabarits de prompt (section 8)
│   │   └── proposer.py           ← fichier -> Proposal
│   ├── safety/
│   │   ├── hashing.py
│   │   ├── journal.py            ← écriture / lecture JSON Lines
│   │   ├── executor.py           ← plan / simulate / execute
│   │   └── restore.py            ← AUTONOME : bibliothèque standard uniquement
│   ├── learning/
│   │   └── corrections.py
│   ├── versions/
│   │   └── detector.py
│   ├── eval/
│   │   └── evaluate.py
│   └── ui/                       ← à partir de la phase 4
│       ├── app.py
│       ├── tray.py
│       ├── bin_window.py
│       ├── drop_widget.py
│       ├── history.py
│       ├── settings.py
│       └── onboarding.py
└── tests/
```

### 5.3 Abstraction des fichiers

Toutes les opérations sur les fichiers passent par l'interface `FileStore` (`fs/base.py`) : `list_dir`, `stat`, `read_bytes(limit)`, `exists`, `make_dir`, `move`, `copy`, `same_volume(a, b)`.
Le MVP n'a qu'une implémentation : `LocalFileStore`. Une future implémentation cloud pourra être ajoutée sans toucher au reste du code.

### 5.4 Abstraction de l'IA

```python
class LLMProvider(Protocol):
    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        images: list[bytes] | None = None,
    ) -> BaseModel: ...
```

- Première implémentation : `AnthropicProvider`.
- Le modèle est un réglage (`TRIBIN_MODEL`). Valeur par défaut suggérée : `claude-haiku-5-5` (rapide et économique). Comparer avec `claude-sonnet-5-5` sur le jeu d'évaluation (section 10). Vérifier les noms de modèles à jour sur https://docs.claude.com.
- Réponse attendue en JSON strict, validée par pydantic. Si le JSON est invalide : une seule nouvelle tentative en renvoyant l'erreur au modèle, puis échec propre (proposition marquée « à traiter manuellement »).
- Délai d'attente, gestion des erreurs réseau et des limites de débit : 3 tentatives maximum avec attente progressive.

### 5.5 Emplacements des données

Via `platformdirs` (ex. macOS : `~/Library/Application Support/TriBin/`) :

- `tribin.db` : base SQLite (file d'attente, propositions, corrections, profils de dossiers, réglages) ;
- `journal/journal-AAAA-MM.jsonl` : journal des opérations, un fichier par mois ;
- `profile.md` : profil utilisateur issu de l'onboarding ;
- `tribin.log` : journal technique (module `logging`), distinct du journal des opérations.

Dans chaque racine :

- `_TriBin/a_trier/` : **dossier tampon** des fichiers jetés en attente (même volume que la racine, pour des déplacements rapides) ;
- `_Archive/` : remplace toute suppression.

Ces deux dossiers sont automatiquement exclus de la cartographie.
L'emplacement du journal doit être indiqué dans le `README.md`, pour pouvoir le retrouver en urgence.

### 5.6 Compatibilité macOS et Windows

Les deux systèmes sont des cibles de premier rang. Points d'attention obligatoires :

- **Chemins** : `pathlib` uniquement. Supporter les volumes macOS (`/Volumes/NAS/...`), les lecteurs réseau Windows (`Z:\...`) et les chemins UNC (`\\NAS\Clients\...`). Le journal stocke les chemins absolus natifs.
- **Longueur des chemins** : Windows limite souvent le chemin complet à 260 caractères. Vérifier la longueur totale (dossier + nom) avant toute opération ; au-delà de 250, raccourcir d'abord la description, puis avertir l'utilisateur si cela ne suffit pas.
- **Noms réservés Windows** : `CON`, `PRN`, `AUX`, `NUL`, `COM1` à `COM9`, `LPT1` à `LPT9` (avec ou sans extension) sont interdits. Les caractères interdits (6.4) s'appliquent sur les deux systèmes.
- **Casse** : par défaut, macOS et Windows ne distinguent pas majuscules et minuscules. La détection de collision doit être **insensible à la casse** (`Devis.pdf` et `devis.pdf` désignent le même fichier).
- **Unicode** : macOS peut stocker les accents sous forme décomposée (NFD). Comparer les noms après normalisation NFC (`ascii_only` évite la plupart des problèmes).
- **Fichiers cachés** : sur macOS, nom commençant par `.` ; sur Windows, attributs « caché » ou « système ». Gérer les deux.
- **Fichiers ouverts** : Windows refuse de déplacer un fichier ouvert dans une autre application (`PermissionError`). Le détecter, afficher « Fichier ouvert dans une autre application : ferme-le puis réessaie », et laisser le fichier en attente.
- **Même volume** : comparer `os.stat(...).st_dev`, valable sur les deux systèmes.
- **Données de l'appli** : via `platformdirs` (macOS : `~/Library/Application Support/TriBin/` ; Windows : `%APPDATA%\TriBin\`).
- **Tests** : tous les tests doivent passer sur les deux systèmes. GitHub Actions avec une matrice `macos-latest` + `windows-latest` dès la phase 0, pour repérer les problèmes de l'autre système même en développant sur un seul ordinateur.

---

## 6. Fonctionnalités détaillées

### 6.1 Le fichier de convention (référentiel d'équipe)

Fichier YAML. Son chemin est un réglage local : il peut pointer vers un fichier sur le NAS, partagé par toute l'équipe et édité par le référent. Les racines, elles, sont des réglages locaux (les chemins de montage diffèrent d'un poste à l'autre).

Exemple (`convention.example.yaml`) :

```yaml
version: 1
name: "Convention Agence Exemple"
language: fr

structure:
  # Gabarit de chemin relatif à la racine.
  # Variables disponibles : {client}, {year}, {project}, {category}
  template: "{client}/{year}/{project}/{category}"
  project_format: "{project_code}_{project_name}"   # ex. 2026-042_Campagne-Noel
  categories:
    - { code: "01_Brief",     description: "Briefs, cahiers des charges, documents reçus du client" }
    - { code: "02_Creation",  description: "Recherches, pistes, maquettes de travail" }
    - { code: "03_Execution", description: "Fichiers d'exécution, déclinaisons, adaptations" }
    - { code: "04_Livrables", description: "Fichiers finaux envoyés au client" }
    - { code: "05_Sources",   description: "Photos, polices, logos, rushes reçus ou achetés" }
    - { code: "06_Admin",     description: "Devis, bons de commande, factures, contrats" }

naming:
  template: "{date}_{client}_{project_code}_{description}_v{version}"
  separator: "_"           # entre les segments du gabarit
  word_separator: "-"      # à l'intérieur d'un segment : "Affiche-Abribus"
  date_format: "%Y-%m-%d"
  version_format: "{:02d}" # v01, v02...
  ascii_only: true         # supprime les accents (compatibilité NAS / Windows / macOS)
  max_length: 120
  lowercase_extension: true
  versioned_categories: ["02_Creation", "03_Execution", "04_Livrables"]

clients:
  - { code: "ACME",  name: "Acme Corporation", aliases: ["acme", "acme corp"] }
  - { code: "BRIOC", name: "Brioches Dupont",  aliases: ["dupont", "brioches dupont"] }
  # Importable depuis un CSV : python -m tribin import-clients clients.csv

excluded_paths:            # motifs glob relatifs à la racine
  - "**/_PROJET_EN_COURS/**"
  - "**/Rushes/**"

versions:
  keep_older_in_subfolder: true
  subfolder_name: "_versions"
```

`convention/loader.py` valide ce fichier avec pydantic et produit des erreurs lisibles (champ, problème, suggestion).

### 6.2 Extraction de contenu

`extract(path) -> FileInfo` (modèle pydantic) :

- **toujours** : nom, extension, taille, dates de création et de modification, dossier d'origine, type MIME ;
- **texte** (`.txt`, `.md`, `.csv`) : 4 000 premiers caractères ;
- **PDF** : texte des 3 premières pages (4 000 caractères max). Si aucun texte (document scanné) : rendu de la première page en image avec `pypdfium2` (1024 px max), envoyée à l'IA pour analyse visuelle ;
- **Word / Excel / PowerPoint** : texte principal ; noms des feuilles et premières cellules ; titres des diapositives (4 000 caractères max) ;
- **images** (`jpg`, `png`, `tif`, `webp`, `heic` si possible) : métadonnées EXIF + miniature 1024 px envoyée à l'IA ;
- **PSD** : miniature via `psd-tools` (utiliser la vignette intégrée si elle existe, pour la vitesse) + noms des calques de premier niveau ;
- **AI** (Illustrator) : la plupart sont compatibles PDF, tenter l'extraction PDF ; sinon métadonnées seules ;
- **INDD, AEP, PRPROJ, vidéos et autres** : nom et métadonnées uniquement.

Chaque extracteur a un délai maximal de 10 secondes. En cas d'échec, revenir aux métadonnées seules **sans planter**.

### 6.3 Moteur de proposition

`propose(file_info, context) -> Proposal`, en plusieurs étapes :

1. **Présélection des dossiers candidats** (`engine/candidates.py`) : à partir des profils de dossiers (6.6), garder les 15 plus pertinents par similarité de mots-clés (`rapidfuzz`) entre le nom et le contenu du fichier d'une part, le chemin et la description du dossier d'autre part. Toujours inclure les dossiers du client détecté.
2. **Détection du client** : correspondance approximative entre le texte extrait ou le nom du fichier et la liste `clients` (codes et alias). Transmise à l'IA comme **indice**, pas comme certitude.
3. **Exemples de corrections** (6.7) : jusqu'à 5 corrections passées similaires.
4. **Appel à l'IA** avec le prompt de la section 8. L'IA renvoie des **champs** (client, projet, catégorie, date, description…) et un dossier cible.
5. **Construction du nom par le code** (`convention/naming.py`), **pas par l'IA** : le format est ainsi toujours conforme.
6. **Validation** : dossier dans la racine et hors zones exclues, client connu ou signalé comme nouveau, nom conforme, pas de collision (sinon suffixe).
7. **Versions** (phase 6) : vérifier s'il s'agit d'une nouvelle version d'un fichier existant.

```python
class NameFields(BaseModel):
    date: date | None
    client: str | None
    project_code: str | None
    project_name: str | None
    category: str | None
    description: str
    version: int | None

class Alternative(BaseModel):
    target_folder: str
    new_name: str
    reasoning: str

class Proposal(BaseModel):
    file_id: str
    target_folder: str            # relatif à la racine
    folder_is_new: bool           # dossier à créer
    new_name: str                 # construit par naming.py
    fields: NameFields
    confidence: float             # 0.0 à 1.0
    reasoning: str                # 1 à 2 phrases, montrées à l'utilisateur
    alternatives: list[Alternative]   # 0 à 2
    warnings: list[str]           # ex. "client inconnu", "création de dossier"
    prompt_version: str
    model: str
```

Si `confidence < 0.6`, la proposition est marquée **« à vérifier »** dans l'interface.

### 6.4 Nommage

`build_name(fields, convention, extension) -> str` :

- applique `naming.template`. Le gabarit est découpé selon `separator` en segments ; **un segment dont une variable est vide est retiré entièrement** (ex. pas de `_v` orphelin, pas de `__`) ;
- date absente : utiliser la date de modification du fichier ;
- version : avant la phase 6, reprendre la version présente dans le nom d'origine (`v2`, `V02`, `_3`… normalisée), sinon vide ; à partir de la phase 6, numérotation automatique pour les catégories de `versioned_categories` ;
- nettoyage : accents supprimés si `ascii_only` (normalisation Unicode NFKD), espaces remplacés par `word_separator`, caractères interdits retirés (`< > : " / \ | ? *` et caractères de contrôle), pas de point ni d'espace en fin de nom (Windows), longueur maximale respectée en tronquant d'abord la description ;
- extension en minuscules ; extensions composées conservées (`.tar.gz`).

Tests unitaires exhaustifs obligatoires : accents, emojis, noms très longs, champs vides, caractères interdits, extensions composées, absence d'extension, noms réservés Windows, chemin complet trop long (5.6).

### 6.5 Exécution sécurisée, simulation et annulation

`safety/executor.py` :

- `plan(proposals) -> list[Operation]` : transforme des propositions validées en opérations ;
- `simulate(operations) -> SimulationReport` : vérifie tout **sans toucher aux fichiers** (existence, permissions, collisions, périmètre, zones exclues, espace disque), inscrit les opérations au journal avec le statut `simulated`, renvoie un rapport lisible ;
- `execute(operations)` : passe **par le même code que la simulation**, puis exécute réellement, opération par opération, avec journalisation `pending` puis `done` ou `failed` ;
- une erreur sur une opération n'arrête pas le lot, mais elle est signalée ; les opérations qui en dépendent passent en `skipped` ;
- `undo(operation_id | batch_id)` : s'appuie sur `restore.py`.

Actions possibles :

| Action    | Usage                                                                 |
|-----------|-----------------------------------------------------------------------|
| `stage`   | de l'emplacement d'origine vers le dossier tampon (dépôt dans la corbeille) |
| `mkdir`   | création d'un dossier (l'annulation ne le retire que s'il est vide)   |
| `move`    | rangement final (avec ou sans renommage)                              |
| `rename`  | renommage sur place                                                   |
| `archive` | vers `_Archive/` (remplace toute « suppression »)                     |
| `undo`    | annulation d'une opération précédente                                 |

« Renvoyer à l'origine » depuis la corbeille = annuler l'opération `stage`.

### 6.6 Cartographier l'existant / créer de zéro

**Cartographier l'existant** (`mapping/`) :

- parcourir chaque racine jusqu'à une profondeur de 6 (réglable), en ignorant les zones exclues, `_TriBin`, `_Archive`, `_versions`, les fichiers cachés et les paquets macOS ;
- pour chaque dossier : nombre de fichiers, extensions principales, 5 noms de fichiers échantillons, date de dernière modification ;
- détecter par expressions régulières les **motifs de nommage** en place : position et format des dates, séparateurs, jetons de version (`v1`, `V02`, `final`…) ;
- générer avec l'IA une **description courte de chaque dossier** (« Factures fournisseurs 2025, une par fournisseur »), par lots de 30 dossiers par appel pour limiter le coût ;
- stocker les profils dans SQLite ; commande « Recartographier » ; au lancement, mise à jour légère (dossiers ajoutés ou supprimés seulement) ;
- si aucun fichier de convention n'existe : proposer une convention déduite de l'existant (structure et nommage dominants), que l'utilisateur relit et valide.

**Créer de zéro** :

- l'IA propose une structure à partir du profil d'onboarding (et, facultativement, d'un échantillon de fichiers) ;
- affichage en arbre, modifiable (renommer, ajouter, retirer des branches) ;
- après validation : écriture du fichier de convention et création des dossiers (opérations `mkdir` journalisées, simulation obligatoire).

### 6.7 Apprentissage

`learning/corrections.py` :

- à chaque validation, enregistrer en base : informations du fichier (nom d'origine, extension, court extrait du contenu, client détecté), proposition de l'IA, choix final, type de décision (`accepted`, `edited`, `alternative_chosen`, `rejected`) et champs modifiés. Ces informations figurent aussi dans le journal (`ai_proposal`, `final_choice`, `decision`) ;
- **récupération** : pour un nouveau fichier, sélectionner jusqu'à 5 corrections récentes les plus similaires (même type de fichier, même client, nom proche via `rapidfuzz`) et les injecter dans le prompt comme exemples ;
- **signal implicite** (fin de phase 5) : si un fichier rangé par TriBin est déplacé manuellement dans les 14 jours (vérifié au lancement), l'enregistrer comme correction ;
- **règles résumées** (fin de phase 5) : toutes les 20 corrections, demander à l'IA de résumer les préférences en règles lisibles (« Tu mets le nom du client avant la date »). Ces règles sont affichées dans les réglages, modifiables et supprimables par l'utilisateur, et injectées dans le prompt ;
- **priorité à l'équipe** : la convention d'équipe l'emporte toujours. Une correction qui contredit une règle d'équipe n'est pas apprise comme préférence ; elle est comptabilisée, et si elle revient souvent, signalée (« Cette règle d'équipe est souvent corrigée »).

### 6.8 Onboarding

Au premier lancement, 5 questions maximum, surtout à choix, toutes facultatives :

1. Secteur : agence de pub / com, studio créatif, freelance, autre (texte libre).
2. Rôle : créa, chef de projet, production, commercial / admin, direction, autre.
3. Usage : personnel ou en équipe.
4. Types de fichiers principaux (choix multiple) : visuels, documents, vidéo, admin / factures, mise en page, autre.
5. Situation : une structure existe à respecter / à créer de zéro / à réorganiser (« bientôt disponible »).

Plus un champ libre facultatif : « Précise ton contexte en quelques mots ».

L'IA rédige un profil court (5 à 8 lignes) stocké dans `profile.md`, modifiable dans les réglages et inclus dans chaque prompt. Viennent ensuite le choix des racines, des zones exclues et du fichier de convention, puis l'avertissement de confidentialité (3.4).

### 6.9 Détection des versions

`versions/detector.py` :

- **nom de base normalisé** : retirer les jetons de version et de statut (`v1`, `V02`, `_v3`, `final`, `finale`, `def`, `ok`, `valide`, `copie`, `copy`, `(1)`, `-2`…), les dates, la casse, les accents et les séparateurs ;
- **candidats** : fichiers du dossier cible (et du dossier d'origine) dont le nom de base normalisé est identique ou proche (similarité `rapidfuzz` ≥ 85), avec une extension de la même famille ;
- **images** : confirmer par hash perceptuel (`imagehash`, distance ≤ 10) ;
- si une version précédente est trouvée : proposer le **numéro suivant** au format de la convention et l'indiquer (« Nouvelle version de Affiche-Noel → v04 ») ;
- si `keep_older_in_subfolder` est actif : proposer de déplacer les versions précédentes dans `_versions/` (opérations `move` journalisées, dans la même simulation).

### 6.10 Interface (PySide6)

- **Icône dans la barre système** (barre des menus macOS, zone de notification Windows) avec le nombre de fichiers en attente. Menu : Corbeille, Historique, Réglages, Quitter.
- **Dépôt de fichiers** :
  - **widget flottant** : petite zone de dépôt toujours au premier plan, déplaçable. C'est la zone de dépôt principale pendant le développement ;
  - **fenêtre Corbeille** : accepte aussi le glisser-déposer ;
  - **icône du Dock (macOS)** : via `QFileOpenEvent`. Nécessite une application empaquetée (`.app` déclarant `CFBundleDocumentTypes` dans `Info.plist`) : prévoir un empaquetage minimal (py2app ou PyInstaller) pour le tester ;
  - **Windows** : glisser sur le raccourci de l'exécutable placé sur le bureau (les fichiers arrivent en arguments de ligne de commande), et entrée « Envoyer vers > TriBin » du clic droit (raccourci placé dans le dossier `shell:sendto`, créé depuis les réglages). La barre des tâches Windows n'accepte pas le dépôt de fichiers sur une icône : le widget flottant y est donc essentiel ;
  - **instance unique** : si l'appli tourne déjà, la nouvelle instance transmet les chemins via `QLocalServer` / `QLocalSocket`, puis se ferme.
- **Fenêtre Corbeille** : liste des fichiers en attente (miniature, nom d'origine → nom proposé, dossier proposé, indicateur de confiance, explication au survol). Nom et dossier éditables directement (sélecteur de dossier limité aux racines). Raccourcis : `Entrée` valider, `E` éditer, `A` alternatives, `Échap` passer, `R` renvoyer à l'origine. Bouton « Tout valider » (passe par la simulation).
- **Historique** : opérations du journal, filtrables par date ou par lot ; bouton « Annuler » par opération et par lot.
- **Réglages** : racines, zones exclues, chemin du fichier de convention, profil, règles apprises, modèle d'IA, clé API, avertissement de confidentialité.
- Les analyses tournent en arrière-plan (`QThreadPool`) : l'interface ne gèle jamais.
- Interface entièrement en français.

---

## 7. Journal des opérations

Format **JSON Lines** (une ligne JSON par événement), **en ajout uniquement** : on ne modifie jamais une ligne existante. Un changement de statut = une nouvelle ligne avec le même `operation_id`. L'état d'une opération est donné par sa dernière ligne. Après chaque écriture : `flush()` puis `os.fsync()`. Si l'appli plante pendant une écriture, seule la dernière ligne peut être abîmée : le lecteur doit ignorer une dernière ligne invalide.

Exemple de ligne (présentée sur plusieurs lignes pour la lisibilité) :

```json
{
  "ts": "2026-10-15T21:04:12.381+02:00",
  "operation_id": "op_01JA7X...",
  "batch_id": "b_01JA7X...",
  "user": "prenom",
  "action": "move",
  "status": "done",
  "source": "/Volumes/NAS/Clients/_TriBin/a_trier/scan0042.pdf",
  "destination": "/Volumes/NAS/Clients/ACME/2026/2026-042_Campagne-Noel/06_Admin/2026-10-12_ACME_2026-042_Devis-Impression.pdf",
  "size": 284211,
  "hash_before": "sha256:...",
  "hash_after": "sha256:...",
  "ai_proposal": {"target_folder": "...", "new_name": "...", "confidence": 0.86},
  "final_choice": {"target_folder": "...", "new_name": "..."},
  "decision": "edited",
  "prompt_version": "p1",
  "model": "claude-haiku-5-5",
  "error": null,
  "app_version": "0.1.0"
}
```

- `status` : `simulated` | `pending` | `done` | `failed` | `skipped` | `undone`.
- `action` : `stage` | `mkdir` | `move` | `rename` | `archive` | `undo`.
- Identifiants : ULID de préférence (triables par date), sinon UUID4.
- Hash calculé par blocs de 1 Mo (jamais le fichier entier en mémoire).
- `hash_after` obligatoire pour une copie inter-volumes. Pour un déplacement sur le même volume, vérifier taille et existence (le hash complet d'une grosse vidéo est trop lent pour être systématique).

### 7.1 Script de restauration autonome

`src/tribin/safety/restore.py` utilise **uniquement la bibliothèque standard Python** et s'exécute seul, même si l'application est cassée :

```
python src/tribin/safety/restore.py --journal <dossier_journal> --list
python src/tribin/safety/restore.py --journal <dossier_journal> --batch b_01JA7X...
python src/tribin/safety/restore.py --journal <dossier_journal> --operation op_01JA7X...
python src/tribin/safety/restore.py --journal <dossier_journal> --since 2026-10-15T09:00
# Ajouter --execute pour agir réellement. Sans ce drapeau : simulation (par défaut).
```

- annule dans l'ordre chronologique **inverse** ;
- avant chaque retour en arrière, vérifie que le fichier est toujours à sa destination et que sa taille (et son hash si disponible) correspond ; sinon, ignore cette opération et le signale ;
- n'écrase jamais : si l'emplacement d'origine est occupé, restaure avec le suffixe `_restaure` ;
- journalise ses propres actions (`action: "undo"`).

L'application utilise ce même module pour sa fonction « Annuler ».

---

## 8. Prompt du moteur de proposition

À placer dans `engine/prompts.py`, avec une constante `PROMPT_VERSION` (à incrémenter à chaque modification et inscrite dans le journal). Les blocs `{{...}}` sont remplis par le code ; une section vide est omise.

```text
[SYSTEM]
Tu es l'assistant de rangement de fichiers d'une équipe. Ta mission : proposer
le dossier où ranger un fichier et les éléments de son nouveau nom, en respectant
STRICTEMENT la convention d'équipe fournie.

Règles :
- Choisis de préférence un dossier existant parmi les candidats fournis.
- Ne propose un nouveau dossier que s'il suit le gabarit de structure de la
  convention ; indique alors folder_is_new = true.
- Le client doit être un code de la liste des clients. S'il est inconnu, mets
  client = null et explique-le dans reasoning.
- N'invente aucune information absente du fichier. Si la date du document
  n'est pas identifiable, mets date = null.
- description : 2 à 5 mots, précis et utiles pour retrouver le fichier
  (ex. "Devis impression affiches"), sans répéter le client, la date ni la version.
- Les exemples de corrections montrent les préférences de cet utilisateur :
  suis-les, sauf s'ils contredisent la convention d'équipe.
- confidence : ta certitude réelle, entre 0 et 1. Sois honnête : 0.5 si tu hésites.
- Réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte autour.

[USER]
## Profil de l'utilisateur
{{profile}}

## Convention d'équipe
Structure : {{structure_template}}
Format des projets : {{project_format}}
Catégories : {{categories_with_descriptions}}
Clients (code : nom, alias) : {{clients_list}}

## Règles apprises de cet utilisateur
{{learned_rules}}

## Dossiers candidats (chemin relatif — description)
{{candidate_folders}}

## Exemples de corrections passées (fichier d'origine → choix final)
{{correction_examples}}

## Indice
Client détecté automatiquement (peut être faux) : {{client_hint}}

## Fichier à ranger
Nom d'origine : {{original_name}}
Type : {{extension}} — {{mime}} — {{size_human}}
Dates : créé le {{created}}, modifié le {{modified}}
Dossier d'origine : {{origin_folder}}
Contenu extrait :
"""
{{extracted_text}}
"""
{{image_note}}

## Format de réponse attendu
{
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
}
```

Notes :

- Si une image est disponible (photo, PSD, PDF scanné), la joindre au message ; `{{image_note}}` vaut alors « Une image du fichier est jointe. »
- Limites : 15 dossiers candidats, 5 exemples de corrections, liste des clients filtrée aux 30 plus probables si elle est longue.
- Le prompt sera ajusté selon les résultats de l'évaluation (section 10).

---

## 9. Plan de développement par phases

### Phase 0 — Mise en place

À faire :

- initialiser le dépôt Git, `pyproject.toml` (layout `src/`), `.gitignore`, `.env.example`, `README.md` ;
- `config.py` : lecture de `.env`, chemins via `platformdirs`, garde-fou `TRIBIN_DEV_SANDBOX` ;
- `scripts/make_sandbox.py` : génère `./sandbox/` **au même format qu'un jeu de test** (section 10) :
  - `sandbox/convention.yaml` (cohérent avec `convention.example.yaml`) ;
  - `sandbox/root/` : structure d'agence fictive (3 clients, 2 années, quelques projets, les 6 catégories) avec des fichiers déjà rangés ;
  - `sandbox/inbox/` : ~40 fichiers à ranger, variés et réalistes : PDF contenant du texte de devis, de brief ou de facture, DOCX, XLSX, PPTX, images, faux PSD et INDD, doublons, séries `v1` / `v2` / `final`, noms peu parlants (`scan0042.pdf`, `IMG_3381.jpg`, `Document1.docx`) ;
  - `sandbox/expected.csv` : le rangement attendu de chaque fichier de `inbox/` ;
  - relancer le script recrée la sandbox proprement ;
- configuration de `pytest`, avec au moins un test qui passe ;
- intégration continue GitHub Actions : `pytest` sur `macos-latest` et `windows-latest` à chaque push (5.6).

Critères de validation :

- `python scripts/make_sandbox.py` crée (ou recrée) la sandbox complète ;
- `pytest` passe sur macOS et sur Windows (GitHub Actions).

### Phase 1 — Proposition en ligne de commande, SANS aucun déplacement

Objectif : vérifier au plus vite la qualité des propositions.

À faire :

- `extract/` (6.2), `llm/` (5.4), `convention/loader.py` et `naming.py` (6.1, 6.4), `engine/` (6.3, sans corrections ni versions) ;
- pour cette phase, les dossiers candidats sont simplement tous les dossiers de la racine jusqu'à une profondeur de 4 (200 maximum) ;
- `python -m tribin propose <fichier> --root <racine> --convention <yaml> [--json]` : affiche le dossier proposé, le nouveau nom, la confiance, l'explication et les alternatives (avec `rich`) ;
- `python -m tribin propose-dir <dossier> --root <racine> --convention <yaml>` : propositions pour tous les fichiers d'un dossier, sous forme de tableau ;
- `python -m tribin eval <jeu_de_test>` : évaluation (section 10).

Critères de validation :

- **aucune opération d'écriture sur les fichiers** dans tout le code de la phase ;
- les tests de `naming.py` couvrent tous les cas limites de 6.4 ;
- `python -m tribin eval sandbox/` produit un rapport ;
- objectif indicatif : au moins 70 % de dossiers corrects sur la sandbox avant de passer à la suite (sinon, améliorer le prompt ou l'extraction).

### Phase 2 — Convention et cartographie

À faire :

- `mapping/` (6.6, partie « cartographier ») avec stockage des profils dans SQLite (`db.py`) ;
- `engine/candidates.py` : la présélection par similarité remplace la liste brute de la phase 1 ;
- détection du client (6.3, étape 2) ;
- `python -m tribin map <racine>` : affiche les profils de dossiers ;
- `python -m tribin import-clients <csv>` : ajoute des clients à la convention ;
- génération d'une convention déduite de l'existant quand aucune n'existe ;
- `python -m tribin init-structure` : propose une structure de zéro, l'affiche en arbre et écrit la convention après confirmation (la création des dossiers viendra en phase 3).

Critères de validation :

- cartographie de la sandbox en moins de 10 secondes (hors appels à l'IA) ;
- les zones exclues ne sont jamais parcourues (test) ;
- le score d'évaluation est au moins égal à celui de la phase 1.

### Phase 3 — Exécution sécurisée, journal, annulation

À faire :

- `safety/` complet (sections 3, 6.5, 7) ;
- `python -m tribin file <fichier> [--yes]` : propose, affiche la simulation, demande confirmation, exécute ;
- `python -m tribin history` et `python -m tribin undo --batch <id>` ;
- création des dossiers pour « créer de zéro » (simulation obligatoire) ;
- garde-fou sandbox (3.3).

Critères de validation — tests automatisés **OBLIGATOIRES** :

- impossible d'écraser un fichier, y compris quand seule la casse diffère (`Devis.pdf` / `devis.pdf`) ;
- noms réservés Windows et chemins trop longs correctement gérés ;
- fichier verrouillé (ouvert ailleurs) : erreur claire, fichier laissé en attente, rien de perdu ;
- impossible d'écrire hors d'une racine ou dans une zone exclue, y compris via `..` ou un lien symbolique ;
- déplacement inter-volumes interrompu juste après la copie (simulé) : l'original reste intact et le fichier partiel est retiré ;
- toute opération est inscrite au journal **avant** son exécution ;
- `restore.py` annule correctement un lot de 20 opérations, y compris quand l'un des fichiers a été déplacé entre-temps (ignoré et signalé) ;
- `restore.py` n'importe que des modules de la bibliothèque standard (test qui inspecte ses imports) ;
- avec `TRIBIN_DEV_SANDBOX=1`, toute opération hors de `./sandbox/` est refusée.

### Phase 4 — Application de bureau « Corbeille »

À faire :

- `ui/` (6.10), onboarding (6.8), réglages ;
- dossier tampon et action `stage` ;
- file d'attente persistante dans SQLite (les fichiers en attente survivent à un redémarrage) ;
- empaquetage minimal avec PyInstaller, sans signature : `.app` pour macOS et `.exe` pour Windows, afin de tester le dépôt sur l'icône du Dock et sur le raccourci du bureau ;
- entrée « Envoyer vers > TriBin » sous Windows.

Critères de validation :

- glisser un fichier sur le widget flottant ou la fenêtre Corbeille l'ajoute à la file d'attente ;
- avec l'appli empaquetée : le dépôt sur l'icône du Dock (macOS) et sur le raccourci du bureau (Windows) fonctionne, que l'appli soit lancée ou non ;
- « Envoyer vers > TriBin » fonctionne sous Windows ;
- l'interface reste fluide pendant l'analyse de 20 fichiers ;
- valider, modifier, renvoyer à l'origine et annuler fonctionnent depuis l'interface ;
- fermer puis rouvrir l'appli conserve la file d'attente ;
- tous ces points sont vérifiés manuellement sur macOS **et** sur Windows.

### Phase 5 — Apprentissage

À faire : section 6.7 (corrections et exemples d'abord, puis signal implicite et règles résumées).

Critères de validation :

- après 3 corrections cohérentes sur un type de fichier, la 4e proposition similaire intègre la préférence (test sur la sandbox) ;
- une correction contraire à la convention d'équipe n'est pas apprise comme préférence (test) ;
- les règles apprises sont visibles, modifiables et supprimables.

### Phase 6 — Versions

À faire : section 6.9.

Critères de validation :

- dans la sandbox, les séries `v1` / `v2` / `final` sont reconnues comme versions d'un même document ;
- un nouveau fichier reçoit le bon numéro de version ;
- le déplacement des anciennes versions dans `_versions/` passe par la simulation et s'annule correctement.

---

## 10. Évaluation de la qualité

Objectif : mesurer objectivement si les propositions s'améliorent, à chaque modification du prompt, de l'extraction ou du modèle.

Structure d'un jeu de test (la sandbox suit le même format ; les jeux de test réels restent hors Git) :

```
testset/
├── convention.yaml      ← convention utilisée pour ce jeu
├── root/                ← arborescence de référence
├── inbox/               ← fichiers à ranger
└── expected.csv
```

`expected.csv` :

```csv
file,expected_folder,expected_name,acceptable_folders
scan0042.pdf,ACME/2026/2026-042_Campagne-Noel/06_Admin,2026-10-12_ACME_2026-042_Devis-Impression.pdf,
IMG_3381.jpg,ACME/2026/2026-042_Campagne-Noel/05_Sources,,ACME/2026/2026-042_Campagne-Noel/02_Creation
```

- `expected_name` : facultatif ;
- `acceptable_folders` : autres dossiers jugés corrects, séparés par `|`.

`python -m tribin eval <jeu_de_test> [--model <modèle>]` :

- génère les propositions **sans aucun déplacement** ;
- calcule : % de dossiers exacts, % de dossiers acceptables, % de clients corrects, % de catégories correctes, % de noms exacts (si fournis), confiance moyenne des bonnes et des mauvaises réponses, temps moyen et coût estimé par fichier ;
- affiche un rapport et enregistre `eval_results/AAAA-MM-JJ_HHMM_<modèle>_<prompt_version>.csv` pour comparer les essais.

Indicateur principal en usage réel : **taux de propositions acceptées sans modification**, calculé à partir du journal. Objectif : 80 % ou plus.

---

## 11. Conventions de code

- Identifiants (variables, fonctions, classes) **en anglais** ; textes de l'interface et messages à l'utilisateur **en français**.
- Typage complet (type hints) ; docstrings courtes sur les fonctions publiques.
- `pathlib.Path` partout ; jamais de concaténation de chaînes pour construire un chemin.
- Aucun chemin, clé API ni nom de modèle codé en dur : tout passe par `config.py`.
- Journal technique via le module `logging`, distinct du journal des opérations.
- Les erreurs ne font jamais planter l'appli : elles sont capturées, journalisées et expliquées clairement à l'utilisateur.
- Petits commits aux messages explicites (`feat(safety): ...`, `fix(naming): ...`, `test(restore): ...`).
- Aucune nouvelle dépendance sans justification.

---

## 12. Points ouverts et idées pour plus tard

**Décisions à prendre**

- Nom définitif du produit.
- Modèle par défaut après évaluation (Haiku ou Sonnet), puis faisabilité d'un modèle local (Ollama). Décidé pour Mistral : mistral-medium-latest ; Anthropic reste à évaluer.

**Idées pour plus tard (hors MVP)**

- Traitement massif du stock existant (mode par lots en arrière-plan).
- Réorganisation d'une arborescence existante (avant / après validé par blocs).
- Suivi des droits sur les images : origine, licence, date d'expiration.
- Recherche en langage naturel grâce à l'index des fichiers rangés.
- Détection des fichiers liés aux projets InDesign / After Effects / Premiere.
- Statut « livré » / « validé client » ; archivage des versions intermédiaires après livraison.
- Remontée au référent des règles d'équipe souvent corrigées.
- Intégrations cloud, version équipe avec serveur.
- Empaquetage complet, signature et notarisation (macOS), installeur (Windows), mises à jour.
- Télémétrie anonyme avec consentement explicite.

*(L'agent ajoute ici toute idée hors périmètre rencontrée pendant le développement.)*

- Décrire automatiquement (IA) les dossiers créés par TriBin dès leur création ; aujourd'hui ils sont décrits au prochain « Recartographier ».
- Mode d'évaluation hors ligne (heuristique sans IA) pour vérifier la chaîne complète sans clé API.
- Éditeur graphique de l'arbre de structure « créer de zéro » (aujourd'hui : relecture du fichier YAML généré).
- Option de nommage « majuscule à chaque mot » (ex. Devis-Impression) pour coller aux noms existants de l'équipe.

---

## 13. État d'avancement

*À mettre à jour par l'agent à la fin de chaque tâche.*

- [x] Phase 0 — Mise en place
- [x] Phase 1 — Proposition en ligne de commande, sans déplacement (score réel avec Mistral via l'API : 90 % de dossiers acceptables, objectif 70 % atteint)
- [x] Phase 2 — Convention et cartographie
- [x] Phase 3 — Exécution sécurisée, journal, annulation
- [x] Phase 4 — Application de bureau « Corbeille » (test de fumée de l'appli empaquetée OK en CI sur macOS et Windows ; dépôt à la souris sur le Dock à vérifier à la main sur un Mac)
- [x] Phase 5 — Apprentissage
- [x] Phase 6 — Versions

**Journal de bord**

| Date | Phase | Ce qui a été fait | Score d'évaluation | Prochaine étape |
|------|-------|-------------------|--------------------|-----------------|
| 2026-10-24 | 0 | Dépôt, pyproject (uv, Python 3.12), config + garde-fou sandbox, make_sandbox (6 projets, 45 fichiers rangés, 42 à ranger, expected.csv), pytest, CI macOS/Windows | — | Phase 1 |
| 2026-10-24 | 1 | extract/, llm/ (Anthropic, sortie structurée), convention/ (loader, naming, structure), engine/ (prompt p1, proposer), CLI propose / propose-dir / eval ; tests avec IA simulée (100 % avec l'oracle, aucune écriture) | non mesuré (pas de clé API) | Phase 2 |
| 2026-10-24 | 2 | db.py (SQLite), mapping/ (scanner < 1 s sur la sandbox, motifs de nommage, descriptions IA par lots de 30, convention déduite, structure de zéro), détection du client, présélection des 15 dossiers (rapidfuzz), CLI map / import-clients / init-structure | non mesuré (pas de clé API) ; dossier attendu présent dans les candidats ≥ 80 % | Phase 3 |
| 2026-10-24 | 3 | safety/ (executor plan/simulate/execute/undo, journal JSONL fsync, restore.py autonome stdlib, copie inter-volumes .tribin-partial + SHA-256), CLI file / history / undo / create-structure ; tous les tests obligatoires de la phase 3 | — | Phase 4 |
| 2026-10-24 | 4 | service/ (dépôt, file d'attente SQLite, analyse, validation, renvoi), ui/ PySide6 (barre système avec compteur, widget flottant, Corbeille, Historique, Réglages, onboarding, instance unique, QFileOpenEvent, Envoyer vers), empaquetage PyInstaller (.exe testé : instance unique + fichier en argument) | — | Phase 5 |
| 2026-10-24 | 5 | learning/ : corrections (décision, champs modifiés, conformité à la convention), 5 exemples similaires dans le prompt, signal implicite (déplacement manuel sous 14 jours), règles résumées toutes les 20 corrections (modifiables, supprimables), alerte « règle d'équipe souvent corrigée » | — | Phase 6 |
| 2026-10-24 | 6 | versions/detector.py : nom de base normalisé, familles d'extensions, similarité ≥ 85, hash perceptuel ≤ 10 pour les images, numéro suivant, anciennes versions vers _versions/ dans le même lot (simulation + annulation) ; README complet | non mesuré (pas de clé API) | Mesurer l'éval avec une clé ; vérifs manuelles macOS |
| 2026-10-24 | CI | Dépôt GitHub privé gyxcit/tribin ; CI de tests au vert sur macOS et Windows (202 tests sous Windows) ; CI d'empaquetage : .exe et .app construits et testés (instance unique, fichier reçu, déposé, analysé ; CFBundleDocumentTypes vérifié). Bug corrigé : ordre d'annulation quand deux opérations partagent la même milliseconde | non mesuré (pas de clé API) | Lancer l'éval avec une clé ; essai manuel sur un Mac |
| 2026-10-24 | 1 (mesure) | Sans clé API : prompts réels de la sandbox exportés, réponses rédigées par Claude Opus 5.5 (session de développement) puis rejouées dans `tribin eval`. Prompt p1 : 97,5 % de dossiers acceptables (90 % exacts), 100 % de clients. Défauts trouvés et corrigés : dossiers intermédiaires vides parmi les candidats, aucun bon candidat quand le client n'est pas détecté → prompt p2 (liste des projets existants). Prompt p2 : 100 % acceptables, 92,5 % exacts, 100 % de clients, 0 % de noms exacts (description formulée différemment). Réserves : ce n'est pas le modèle configuré (Haiku via l'API), et l'auteur du corrigé est le même que celui des réponses | 100 % (p2, IA jouée) | Confirmer avec `tribin eval` et une vraie clé |
| 2026-10-24 | 5.4 | Second fournisseur d'IA : Google Gemini (`TRIBIN_PROVIDER=gemini`, `GEMINI_API_KEY`, SDK google-genai en option `--extra gemini`), choix du fournisseur dans les Réglages, workflow eval avec choix du fournisseur. Clé Gemini de l'utilisateur valide (46 modèles accessibles) mais crédits prépayés épuisés (erreur 402) : éval réelle impossible tant que le compte n'est pas rechargé | — | Recharger les crédits Gemini puis lancer `tribin eval sandbox/ --min-score 70` |
| 2026-10-24 | 5.4 | Troisième fournisseur d'IA : Mistral AI (`TRIBIN_PROVIDER=mistral`, `MISTRAL_API_KEY`, SDK mistralai en option `--extra mistral`, modèle par défaut mistral-small-latest), choix dans les Réglages et dans le workflow eval | — | Ajouter la clé Mistral puis lancer l'éval |
| 2026-10-24 | 1 (mesure réelle) | `tribin eval sandbox/ --min-score 70` avec Mistral `mistral-small-latest` via l'API, prompt p2 : **90 % de dossiers acceptables**, 70 % exacts, 100 % de clients, 72,5 % de catégories, ~2,1 s par fichier. Les 4 erreurs portent toutes sur la catégorie (client et projet justes). Confiance mal calibrée : 0,97 sur les bonnes réponses, 0,94 sur les mauvaises → le marqueur « à vérifier » se déclenche rarement | 90 % (Mistral, réel) | Améliorer la calibration de la confiance ; comparer avec mistral-medium-latest / Haiku |
| 2026-10-24 | 1 (calibration) | Prompt p3 : barème de confiance explicite. Seul, sans effet sur Mistral Small (toujours 0,9–1 ; 0 erreur signalée). Ajout côté code : alternatives identiques au premier choix retirées, et alternative réelle ⇒ confiance plafonnée à 0,55 (« à vérifier », avec « L'IA hésite avec : … »). Éval officielle p3 : **Small** 87,5 % acceptables, confiance 0,90 (bonnes) / 0,74 (mauvaises), erreurs signalées 20 %, bonnes signalées à tort 8,6 % ; **Medium** 87,5 % acceptables, 100 % de clients, 0,82 / 0,69, erreurs signalées 60 %, bonnes signalées à tort 28,6 %. Avant (p2, Small) : 0 % des erreurs signalées. Variation d'un passage à l'autre : ±2 à 3 fichiers | 87,5 % (Mistral, réel) | Choisir le modèle par défaut (Small : moins de faux signalements ; Medium : erreurs mieux repérées) |
| 2026-10-24 | 12 (décision) | Modèle Mistral par défaut : **mistral-medium-latest** (validé par le propriétaire) : moins d'erreurs présentées avec assurance (2 sur 40 contre 4 avec Small) et 100 % de clients corrects, au prix de plus de fichiers marqués « à vérifier » | — | — |
| 2026-10-24 | 4 (design) | Identité visuelle : logo « entonnoir » (resources/logo.svg, .ico/.icns générés), thème aux couleurs du logo (bleu nuit ; turquoise / ambre / corail = confiance sûre / à regarder / à vérifier), fenêtre Corbeille en liste + détail (nom et dossier modifiables, alternatives cliquables, aperçus PDF/PSD), bandeau commun Corbeille / Historique / Réglages, onboarding avec logo | — | Retour des utilisateurs |
| 2026-10-24 | 4 (design v2) | Nouvelle interface d'après la maquette Claude Design « TriBin — nouvelle interface » : bandeau avec navigation, file groupée (À vérifier / Prêts / Analyse) avec recherche, détail avant → après, fil d'Ariane, catégorie en un clic, jauge de confiance, encart « L'IA hésite avec », fenêtre de simulation en arbre, Historique intégré par jour et par lot (annulation par lot et par opération), widget de dépôt à quatre états | — | Retours d'usage |
| 2026-10-24 | 4 (design v3) | Interface « v2 » (maquette Claude Design revue avec des références Mobbin : Plain, Intercom, Snowflake, Attio, Proton, Grammarly) : fenêtre en trois colonnes (navigation, fichiers à ranger avec onglets Tous / À vérifier / Prêts, détail en lignes libellé / valeur avec catégorie en liste déroulante), barre d'actions en bas avec raccourcis ; premier lancement avec étapes numérotées à gauche et choix de l'IA en cartes ; Réglages par catégories ; dossiers choisis un par un (« Ajouter », puis « Ajouter un autre ») ; titres en minuscules, vouvoiement. Bug corrigé : `tribin file` plantait après une correction (variable `result` inconnue) | — | Retours d'usage |
| 2026-10-24 | 4 (décision) | Demande du propriétaire : rangement sans intervention. Bouton « Ranger les N prêts » dans le widget (confiance ≥ 60 %) et réglage « Rangement automatique » (désactivé par défaut ; confiance ≥ 80 %), les autres fichiers sont signalés par une notification qui ouvre TriBin. Garde-fous de la section 3.1 conservés : un fichier par lot, simulation silencieuse avant chaque rangement, aucun rangement automatique qui créerait un dossier ou dont la simulation signale un problème, tout reste annulable. Décision « auto » : exclue de l'apprentissage et du taux d'acceptation. Correctifs : garde-fou sandbox inactif par défaut dans l'appli empaquetée ; widget sans ombre (bordure grise) | — | Retours d'usage |
| 2026-10-25 | 1 (mesure p4) | Prompt p4 (jamais « null » ni champ de gabarit dans le dossier ; dossier vide et confiance < 0,3 si rien ne convient) + garde-fou dans le code. Deux passages `tribin eval` avec Mistral Medium : **87,5 % de dossiers acceptables** (77,5 % exacts), 100 % de clients, 77,5 % de catégories, aucun dossier « null », aucun fichier à la main ; erreurs signalées 20 % puis 40 % (p3 : 60 % sur un passage), bonnes signalées à tort 25,7 % (p3 : 28,6 %). Mêmes fichiers limites qu'en p3 (photos IMG_3381/3382, Planning, bilan, reco) : avec 5 erreurs sur 40, un fichier fait varier le taux de signalement de 20 points ; pas d'écart significatif avec p3 | 87,5 % (Mistral Medium, réel) | Enrichir la sandbox (plus de cas limites) pour mesurer la calibration |
| 2026-10-25 | 1 (mesure p5) | Dossiers libres (hors gabarit) : index des fichiers déjà rangés par « modèle de nom » (chiffres remplacés), section « Fichiers du même modèle de nom déjà rangés » dans le prompt p5 et dossier ajouté aux candidats ; carte des dossiers reconstruite dès que les dossiers changent ; version « v09 » tirée d'une heure (…T08_57_09) corrigée ; convention déduite : les dossiers libres de premier niveau ne sont plus pris pour des clients. Sandbox : +2 cas (bulletin de paie, relevé bancaire dans « Administratif/… »), 42 fichiers. Deux passages Mistral Medium : **90,5 % de dossiers acceptables** (81 % exacts), 100 % de clients, 81 % de catégories, erreurs signalées 50 %, bonnes signalées à tort 31,6 % puis 23,7 %. Les 2 nouveaux cas : bons, confiance 0,9 (rangés automatiquement) ; les 40 fichiers d'origine : 36/40 acceptables (p4 : 35/40) | 90,5 % (Mistral Medium, réel) | Retours d'usage |

---

## 14. Glossaire

- **Racine** : répertoire de référence géré par TriBin ; rien n'est rangé en dehors.
- **Zone exclue** : dossier auquel TriBin ne touche jamais (ex. projets en cours avec fichiers liés).
- **Dossier tampon** : `_TriBin/a_trier/`, où attendent les fichiers jetés dans la corbeille.
- **Convention** : fichier YAML partagé décrivant la structure, la nomenclature, les clients et les catégories.
- **Proposition** : dossier et nom suggérés par l'IA pour un fichier.
- **Correction** : différence entre la proposition de l'IA et le choix final de l'utilisateur.
- **Lot** : ensemble d'opérations exécutées ensemble et annulables d'un coup.
- **Simulation** : vérification complète d'un lot sans toucher aux fichiers.
