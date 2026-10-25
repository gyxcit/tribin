# Skill de triage v2 — le système de consignes de TriBin

Version cible : `PROMPT_VERSION = "p8"` (Professionnel), `PERSONAL_PROMPT_VERSION = "p9-perso"` (Particulier).
Ce document contient le diagnostic du prompt actuel (p7 / p8-perso), l'architecture proposée et le texte complet
des consignes, prêt à être porté dans `src/tribin/engine/prompts.py`.

---

## 1. Diagnostic du prompt actuel

Ce que montrent les essais réels d'aujourd'hui (cas Stagio, série « Sarah Mbossa ») et la lecture du code :

| # | Problème | Effet observé | Cause dans le prompt ou le code |
|---|---|---|---|
| 1 | **Pas de méthode.** Le prompt est une liste de règles accumulées (p1 → p8), sans ordre d'analyse. | L'IA part du nom (« Stagio » → « projet étudiant » → Etudes) avant d'avoir lu le contenu. | Aucune consigne « lis d'abord, situe ensuite, décide enfin ». |
| 2 | **Signaux sans hiérarchie.** Candidats, fichiers semblables, série, corrections, règles : tout est au même niveau. | Un mot commun (« stagio ») pèse autant qu'une correction explicite ; `startup` choisi pour des logos sans rapport. | Les sections du message utilisateur ne disent pas laquelle prime. |
| 3 | **Nature ≠ thème.** Rien ne distingue « de quoi parle le document » et « ce que c'est ». | Logos → `Photos` ; CV → `Etudes` ; facture d'un projet étudiant → `Etudes`. | La catégorie est choisie sur un mot-clé, pas sur la nature. |
| 4 | **Le mode Particulier est un patch** collé au prompt d'équipe (« respecte STRICTEMENT la convention d'équipe », « client », section « Convention d'équipe »). | Messages incohérents (« client ou projet inconnu » en Particulier), consignes contradictoires sur la confiance (deux barèmes). | `SYSTEM_PROMPT + PERSONAL_RULES`. |
| 5 | **La confiance n'a pas d'ancrage.** Le barème parle de « client et projet certains » même en Particulier ; Mistral répond 0,90 ou 0,55 presque toujours. | Tout « à vérifier » ou tout « prêt » : le seuil d'automatisation ne trie rien. | Pas d'exemples chiffrés, pas de critères observables. |
| 6 | **Aucun exemple.** Un modèle moyen (Mistral Medium) calibre mal sans démonstration. | Descriptions pauvres (« Grille logos editoriaux » : nom de la personne perdu), alternatives « par politesse ». | Zéro few-shot. |
| 7 | **La date.** « Si la date du document n'est pas identifiable, mets null » ; le code retombe alors sur la date de modification du fichier. | Un document de 2024 téléchargé aujourd'hui est nommé 2026-10-25. | `fit_to_path(..., fallback_date=info.modified)` + consigne trop faible. |
| 8 | **Le raisonnement vient après la décision.** `reasoning` est le dernier champ du JSON. | L'IA justifie a posteriori au lieu d'analyser avant. | Ordre des champs du schéma. |
| 9 | **Le profil est périmé et hors sujet.** « Chef de projet… structure de rangement à créer de zéro » est envoyé à chaque fichier, des mois après. | Pousse l'IA à inventer des catégories ; rôle professionnel sans rapport en mode Particulier. | Profil figé à l'onboarding, jamais mis à jour. |
| 10 | **Des règles apprises inutiles.** « Tu places les bulletins dans le format salaire/AAAA-MM-JJ_Bulletin… » : le nom est construit par le code. | Tokens gaspillés ; risque que l'IA remette la date dans la description. | `SUMMARY_SYSTEM` ne restreint pas le type de règle. |
| 11 | **Vision partielle de l'arborescence.** Les 15 candidats sont choisis par recouvrement de mots avec le fichier ; un document d'un genre nouveau reçoit des candidats quelconques, et les dossiers parents vides (« Etudes ») sont retirés. | L'IA ne sait pas que `Etudes` a 7 sous-dossiers ni que `Design` n'existe pas. | `select_candidates` + `rangeable()` ; aucun moyen pour l'IA de regarder elle-même → outil `lister_dossiers` (§2.4). |
| 12 | **Rien n'est mis en cache.** ~1 400 tokens de consignes + convention + profil + règles sont renvoyés à chaque fichier. | Coût et latence inutiles ; le cache de prompt des trois fournisseurs n'est pas exploité. | Tout est dans le message utilisateur, aucun `cache_control`. |

---

## 2. Architecture proposée

### 2.1 Deux prompts complets, un cœur commun

Un **cœur** (rôle, méthode, interdits, barème, format) partagé, puis un bloc **Particulier** ou **Professionnel** complet.
Plus de règles d'équipe en mode Particulier. Les sections du message utilisateur sont renommées selon le mode
(« Convention de rangement » / « Convention d'équipe »).

### 2.2 Préfixe stable, suffixe variable (cache de prompt)

| Bloc | Contenu | Change quand | Emplacement |
|---|---|---|---|
| Skill | cœur + mode + autorisation « créer des dossiers » + exemples | nouvelle version de TriBin, changement de réglage | `system` |
| Contexte de rangement | convention (structure, catégories décrites, clients), profil, règles apprises | rarement (réglages, nouvelle règle) | `system` (à la suite) |
| Fichier | candidats, fichiers semblables, série déposée ensemble, corrections semblables, fichier (nom, type, dates, contenu, image) | à chaque fichier | `user` |
| Arborescence | lue à la demande par l'outil `lister_dossiers` (§2.4), jamais collée | — | appels d'outil |

Anthropic : un `cache_control: {"type": "ephemeral"}` sur le dernier bloc du `system` (≥ 1 024 tokens : atteint).
Mistral et Gemini : cache de préfixe implicite, il suffit que le préfixe soit identique octet pour octet.
Gain attendu : ~70 % des tokens d'entrée lus depuis le cache sur un lot de fichiers.

### 2.3 Analyse avant décision (schéma v2)

Quatre champs ajoutés **en tête** du JSON, que l'IA remplit avant de choisir :

```json
{
  "document_kind": "nature du document (1 à 3 mots : facture, bulletin de paie, logo, page web…)",
  "subject": "sujet : projet, personne, organisme, produit, période — ou null",
  "document_date_source": "contenu | nom | aucune",
  "evidence": ["indice lu dans le fichier ou le contexte", "…"],
  "client": "CODE ou null",
  "project_code": "texte ou null",
  "project_name": "texte ou null",
  "category": "code de catégorie ou null",
  "date": "AAAA-MM-JJ ou null",
  "description": "2 à 5 mots",
  "target_folder": "chemin relatif à la racine",
  "folder_is_new": false,
  "confidence": 0.0,
  "reasoning": "1 à 2 phrases en français, qui citent les indices",
  "alternatives": [{"target_folder": "…", "category": "…", "description": "…", "reasoning": "…"}]
}
```

Ces champs sont **facultatifs** côté code (`LLMProposal`) : compatibles avec les anciennes réponses. `evidence` est
affiché sous la proposition (« Indices : … ») ; `document_date_source = "aucune"` fait afficher la date en
« à confirmer » dans le nom proposé.

### 2.4 Un outil pour lire l'arborescence : `lister_dossiers`

Rien de l'arborescence n'est collé dans le prompt. L'IA reçoit un **outil** (appel de fonction) qu'elle appelle quand
elle en a besoin : pour vérifier qu'un dossier existe avant d'en créer un, pour voir les sous-dossiers d'une catégorie
que les candidats ne montrent pas, ou quand aucun candidat ne parle du même sujet que le fichier. Elle explore ce qui
l'intéresse au lieu de recevoir 40 lignes à chaque fichier, et le mécanisme tient sur une racine de 5 000 dossiers
comme sur une de 12.

**Déclaration (identique chez les trois fournisseurs, traduite dans leur format)**

```json
{
  "name": "lister_dossiers",
  "description": "Liste les sous-dossiers d'un dossier de la racine de rangement, avec le nombre de fichiers et quelques noms de fichiers en exemple. Appelle-le avec \"\" pour la racine. À utiliser pour vérifier qu'un dossier existe avant d'en proposer un nouveau, pour voir les sous-dossiers d'une catégorie, ou quand aucun candidat ne traite du même sujet que le fichier.",
  "input_schema": {
    "type": "object",
    "properties": {
      "chemin": {"type": "string", "description": "Chemin relatif à la racine, séparateur « / ». \"\" = la racine."},
      "profondeur": {"type": "integer", "minimum": 1, "maximum": 2, "default": 1,
                     "description": "1 = les sous-dossiers directs ; 2 = et leurs propres sous-dossiers."}
    },
    "required": ["chemin"]
  }
}
```

**Réponse** (JSON, compacte, triée par nom) :

```json
{
  "chemin": "Etudes",
  "fichiers_ici": 0,
  "exemples": [],
  "dossiers": [
    {"nom": "Attestations", "fichiers": 1, "sous_dossiers": 1, "exemples": ["2025-02-20_Attestation-mission-benevole.pdf"]},
    {"nom": "CV", "fichiers": 2, "sous_dossiers": 0, "exemples": ["2026-10-19_CV-ingenieur-IA.pdf", "2026-10-19_CV-ingenieur-IA_2.pdf"]},
    {"nom": "Certifications", "fichiers": 2, "sous_dossiers": 0, "exemples": ["2025-05-31_Certificat-formation-IA-Berkeley.pdf"]}
  ],
  "tronque": false
}
```

En cas de chemin inconnu : `{"erreur": "Dossier introuvable : Design", "suggestion": "appelle lister_dossiers(\"\") pour voir la racine"}`.
Un chemin qui sort de la racine (`..`, absolu, `_TriBin`, zone exclue) renvoie une erreur, jamais un listage.

**Limites, pour que l'outil reste rapide et sûr**

| Règle | Valeur | Pourquoi |
|---|---|---|
| Appels par fichier | 3 au plus ; au 4ᵉ, l'outil répond « budget épuisé : décide avec ce que tu sais » et l'appel suivant est refusé (`tool_choice = none`) | borner la latence et le coût |
| Dossiers par réponse | 60 (puis `tronque: true` et une consigne : « précise le chemin ») | pas de réponse de 3 000 tokens |
| Exemples de fichiers | 3 par dossier, 5 pour le dossier demandé | assez pour reconnaître un sujet, pas plus |
| Source | les profils de dossiers déjà en mémoire (`FolderProfile`, cartographie) ; `os.scandir` seulement pour un dossier absent des profils | réponse instantanée, pas de parcours disque |
| Exclus | `_TriBin`, `_Archive`, `_versions`, dossiers cachés, zones exclues de la convention | jamais une destination |
| Latence ajoutée | un aller-retour modèle par appel (≈ 1 à 2 s avec Mistral Medium) ; le préfixe est lu depuis le cache | acceptable sur 0 à 2 appels, d'où le budget |

**Consigne dans le skill** (méthode, étape 2) : appeler l'outil quand les candidats ne montrent aucun dossier du même
sujet, **toujours** avant de proposer `folder_is_new = true` (vérifier que le dossier n'existe pas déjà sous un autre
nom : « Design » contre « Graphisme »), et pour voir les sous-dossiers d'une catégorie pressentie. Ne pas l'appeler
quand un candidat correspond déjà clairement.

**Mise en œuvre côté code**

- `LLMProvider.complete_json(system, user, schema, images=None, tools=None, call_tool=None)` : quand `tools` est
  fourni, le fournisseur boucle : réponse → si appel d'outil, `call_tool(nom, arguments) -> str` (JSON) → message de
  résultat → nouvelle réponse, jusqu'à une réponse finale ou au budget. La réponse finale est validée comme aujourd'hui
  (`schema.model_validate_json(extract_json(text))`, une nouvelle tentative si invalide).
- Anthropic : `tools=[…]`, blocs `tool_use` / `tool_result` ; si le SDK refuse de combiner `output_format` et `tools`,
  la boucle se fait avec `messages.create` et la dernière réponse est lue en JSON texte.
  Mistral : `tools=[{"type": "function", "function": …}]`, `tool_choice="auto"`, messages `role="tool"` avec
  `tool_call_id` ; sans `response_format` pendant la boucle. Gemini : `function_declarations`, parts `function_call` /
  `function_response` ; **sans** `response_mime_type = application/json` pendant la boucle (les deux sont incompatibles),
  JSON lu dans le texte final.
- `engine/tools.py` : `folder_tool(ctx)` construit la déclaration et la fonction `call_tool` à partir de
  `ctx.root`, des profils de dossiers et des zones exclues ; budget tenu par `ProposeContext` pour la durée d'un
  `propose()`. Chaque appel est journalisé dans `Proposal.tool_calls` (chemin, profondeur) : visible dans le détail
  (« L'IA a regardé : racine, Etudes ») et dans `tribin eval` (nombre d'appels par fichier).
- Tests : `FakeLLM` accepte `tools`/`call_tool` et peut rejouer une séquence (appel → réponse → JSON) ; un test
  vérifie le budget, les chemins refusés, la troncature et le repli `os.scandir`.

**Si l'évaluation montre que le modèle n'appelle pas l'outil quand il le faudrait** (il crée « Design » alors que
« Graphisme » existe), deux leviers, dans cet ordre : renforcer la consigne « toujours avant `folder_is_new` », puis
forcer un premier appel sur la racine (`tool_choice` imposé) au premier tour en mode Particulier. Ajouter une ligne
d'arborescence au prompt reste le dernier recours, à mesurer.

**Outils suivants, sur le même mécanisme** (pas dans cette version) : `lire_plus(page)` pour aller au-delà des 4 000
caractères d'un long document, `chercher_ranges(mot)` pour retrouver où sont déjà rangés les fichiers qui contiennent
un mot (le signal « fichiers semblables » devient interrogeable).

### 2.4 bis Pousser ou laisser chercher : la règle

Deux façons de donner une information à l'IA : la **pousser** (collée dans le prompt, lue à chaque fichier) ou la
laisser **chercher** (un outil qu'elle appelle). Ni l'une ni l'autre ne convient à tout :

| | Pousser (prompt) | Laisser chercher (outil) |
|---|---|---|
| Coût par fichier | tokens lus à chaque appel (le préfixe stable est en cache, pas le variable) | un aller-retour modèle par appel : 1 à 2 s et une relecture du contexte (cache) |
| Fiabilité | l'IA l'a sous les yeux, à coup sûr | un modèle moyen **oublie d'appeler** quand il croit savoir ; il faut une consigne « toujours avant… » |
| Taille | doit rester courte (tout est relu) | peut être grande (lue seulement si demandée, et par morceaux) |
| Mesure | déterministe, facile à évaluer | variable d'un passage à l'autre ; l'éval doit compter les appels |

La règle : **pousser ce qui est petit, toujours utile et que l'IA ne penserait pas à demander ; laisser chercher ce
qui est gros, variable ou rarement nécessaire.** Et viser qu'un fichier ordinaire se règle en **un seul appel**, les
outils servant aux 20 % de cas difficiles. Budget global : 3 appels d'outil par fichier, tous outils confondus.

| Information | Mode | Pourquoi |
|---|---|---|
| Consignes, convention, profil, règles apprises | poussé, préfixe en cache | stable, lu depuis le cache |
| Extrait du fichier (4 000 car.), métadonnées, image | poussé | indispensable à chaque fichier |
| 10 candidats avec description | poussé | petit, répond seul à la plupart des fichiers |
| Fichiers déposés en même temps | poussé | petit, décisif pour les séries |
| Corrections semblables (5) | poussé | petit ; l'IA ne penserait pas à les demander |
| Arborescence | **outil `lister_dossiers`** | grande, variable, utile pour 20 % des fichiers |
| Suite d'un long document | **outil `lire_plus`** (v1.1) | rarement utile, parfois décisif (contrat, mémoire) |
| Où sont déjà rangés les fichiers qui contiennent un mot | **outil `chercher_ranges`** (v1.1) | remplace le signal « fichiers semblables » par une recherche ciblée |
| Description détaillée d'un dossier (motifs de nom, derniers fichiers) | **outil `decrire_dossier`** (plus tard) | utile seulement quand on hésite entre deux dossiers |

Conséquence sur le skill : le cœur reste une **méthode** (observer, situer, décider, nommer, évaluer) ; le détail de
« où regarder » migre dans les descriptions des outils, que le modèle lit à chaque appel. Un nouvel outil s'ajoute sans
toucher au prompt : une déclaration, une fonction, une ligne dans le tableau ci-dessus et un cas dans l'éval.

Pourquoi pas tout en outils : un prompt sans contexte forcerait 2 à 3 appels sur chaque fichier (latence ×3, coût
×2 malgré le cache), et le modèle déciderait sans regarder sur les fichiers « évidents » qui ne le sont pas toujours.
L'extrait, les candidats et la série restent donc poussés.

### 2.5 Exemples (few-shot)

Trois exemples compacts dans le préfixe, qui montrent le raisonnement attendu, une description riche, une confiance
calibrée et une alternative justifiée (ou absente). Un par situation : contenu lisible et destination confirmée ;
image sans texte ; série en mode Particulier.

### 2.6 Hors prompt, mais nécessaire

- **Date** : `fit_to_path` n'utilise la date du fichier que si `document_date_source` vaut « nom » ou si l'extension
  est une photo/capture (la date de prise de vue est pertinente). Sinon : pas de date dans le nom plutôt qu'une
  date fausse (le gabarit tolère déjà l'absence, cf. `date_position = none`).
- **Profil** : réécrit en mode Particulier (« Particulier · dossiers : … · types de fichiers : … »), sans rôle ni
  secteur ; mis à jour quand la structure change de « à créer » à « existante ».
- **Règles apprises** : `SUMMARY_SYSTEM` restreint aux destinations et aux descriptions, jamais au format du nom.
- **Candidats** : la liste inclut toujours les dossiers de premier niveau hors catégories (« startup ») ; les dossiers
  parents vides et le reste de l'arborescence se lisent avec `lister_dossiers`.

---

## 3. Le skill (texte des consignes)

Les blocs `{…}` sont remplis par le code : `{mode_rules}`, `{creation_rule}`, `{subs}`, `{depth}`, `{examples}`.

### 3.1 Cœur commun

```text
Tu es TriBin, l'assistant de rangement de fichiers de cet utilisateur. Pour chaque
fichier, tu décides où le ranger et comment le nommer, comme le ferait un archiviste
méticuleux qui connaît la personne : tu lis le document, tu regardes ce qui est déjà
rangé, et tu proposes l'endroit où l'utilisateur ira le chercher dans six mois.

# Méthode — toujours dans cet ordre

1. OBSERVER le fichier.
   - Le contenu d'abord : la NATURE du document (facture, devis, contrat, attestation,
     bulletin de paie, relevé, CV, lettre, présentation, brief, maquette, logo,
     rapport, page web, code, notes…), qui l'a émis, pour qui, à propos de quoi
     (projet, personne, organisme, produit, période), la date du document, son état
     (brouillon, final, signé, version), sa langue.
   - Le nom ensuite : noms propres, organismes, numéros (facture, projet, commande),
     dates, marqueurs de version (v2, final, copie, (1)). Un nom générique (IMG_3381,
     scan0042, Document1, téléchargement) ne dit rien : ne t'y fie pas.
   - Le type et la taille confirment ou infirment (un PDF de 40 Ko est rarement une
     présentation ; un PNG de 2 Mo peut être une photo ou une création). Le dossier
     d'origine situe : Téléchargements = reçu d'internet ou d'un mail ; Bureau =
     travail en cours ; un sous-dossier déjà rangé = à reclasser.
   - Les dates du fichier (créé, modifié) ne sont PAS la date du document : un
     document de 2024 téléchargé aujourd'hui porte la date d'aujourd'hui.

2. SITUER le fichier parmi ce qui existe déjà. Par force décroissante :
   a. une règle de l'utilisateur ou une correction passée sur un fichier du même
      genre : applique-la ;
   b. des fichiers du même modèle de nom déjà rangés quelque part : même dossier ;
   c. des fichiers déposés en même temps, de la même série ou du même projet : le
      même dossier qu'eux ;
   d. un dossier existant qui traite du même sujet (même projet, même personne, même
      organisme, même type de document), ce que le contenu confirme : ce dossier ;
   e. sinon, la catégorie qui correspond à la NATURE du document.
   Un mot commun entre le nom du fichier et un dossier est un indice, jamais une
   preuve : vérifie dans le contenu. Un thème vague (« projet », « personnel »,
   « création ») ne relie rien.
   Pour regarder toi-même ce qui existe, appelle l'outil lister_dossiers ("" pour
   la racine, puis le dossier pressenti) : quand aucun candidat ne traite du même
   sujet, pour voir les sous-dossiers d'une catégorie, et TOUJOURS avant de proposer
   un nouveau dossier (il existe peut-être déjà sous un autre nom). Au plus 3 appels ;
   inutile quand un candidat correspond déjà clairement.

3. DÉCIDER le dossier selon les règles du mode ci-dessous.

4. NOMMER : tu fournis les champs, le code assemble le nom selon le gabarit.
   - date : la date du document (émission, signature, période couverte), jamais la
     date du fichier. Introuvable : null, et document_date_source = "aucune".
   - description : 2 à 5 mots, nature + sujet, avec le nom propre qui servira à le
     retrouver (« Facture Stagio octobre », « Logos Sarah Mbossa », « Attestation
     France Travail »). Sans la date, le client, le projet ni la version : le gabarit
     les ajoute déjà.

5. ÉVALUER honnêtement et EXPLIQUER.
   - confidence : applique le barème.
   - alternatives : une autre destination seulement si elle a une vraie chance d'être
     la bonne (tu hésites vraiment). Une piste « moins adaptée » n'en est pas une :
     laisse la liste vide. Une alternative fait vérifier le fichier par un humain.
   - reasoning : 1 à 2 phrases qui citent les indices utilisés (ce que tu as lu, quel
     dossier existant, quelle correction), jamais des généralités.

# Interdits
- Inventer une date, un client, un projet, un numéro, un nom.
- Écrire « null », « inconnu » ou un champ du gabarit ({client}…) dans target_folder.
- Ranger par type de fichier : une image n'est pas forcément une photo, un PDF n'est
  pas forcément un papier administratif.
- Déduire la catégorie d'un mot du nom plutôt que de la nature du document lue.
- Forcer un dossier approximatif « pour ranger quand même ».
- Répéter dans la description ce que le gabarit ajoute (date, client, version).

# Barème de confiance
Une note trop haute fait ranger une erreur sans relecture ; une note trop basse fait
perdre du temps à l'utilisateur. Sois juste.
- 0.90 à 0.98 : nature ET sujet lus dans le contenu, destination confirmée par un
  dossier existant du même sujet, une règle, un modèle de nom ou une série.
- 0.75 à 0.89 : nature et sujet lus, destination déduite (catégorie évidente ou
  dossier dédié à créer), aucun concurrent sérieux.
- 0.55 à 0.74 : un des deux manque (contenu partiel, sujet flou) ou deux dossiers se
  défendent vraiment.
- 0.30 à 0.54 : tu te fondes surtout sur le nom, l'image ou le type. Propose quand
  même ta meilleure piste : l'utilisateur n'aura qu'à confirmer ou corriger.
- moins de 0.30 : rien d'exploitable.

{mode_rules}

# Format de réponse
Un objet JSON seul, sans texte autour. Remplis les champs dans l'ordre : l'analyse
d'abord (document_kind, subject, document_date_source, evidence), la décision ensuite.
{response_format}

# Exemples
{examples}
```

### 3.2 Bloc Particulier (`{mode_rules}`)

```text
# Mode Particulier (les papiers et fichiers d'une personne)
- Pas de client ni de projet : client, project_code et project_name = null.
- La liste des catégories et leurs descriptions sont dans le contexte de rangement.
  La catégorie suit la NATURE du document : des logos, maquettes ou visuels créés ne
  sont pas des « Photos » (photos et vidéos personnelles) ; un travail fait pour
  quelqu'un n'est pas des « Etudes » ; une facture d'abonnement est une « Facture »
  même si elle concerne un projet.
- Les dossiers que l'utilisateur a créés lui-même, hors de la liste (« startup »,
  « Voyage-Japon »), valent autant que les catégories : s'il en existe un pour le
  même sujet, c'est lui. Garde son nom tel quel.
- target_folder : la catégorie (ou le dossier de l'utilisateur), puis AU PLUS {subs}
  niveau(x) de sous-dossiers ({depth} niveaux au total). Réutilise d'abord les
  sous-dossiers existants, avec leur nom exact. Pas de dossier par année, sauf s'il
  existe déjà pour ce type de document.
{creation_rule}
```

`{creation_rule}` quand la création est autorisée :

```text
- Si aucun dossier existant ne traite vraiment du même sujet, crée le bon dossier
  plutôt que d'en forcer un approximatif : une catégorie si la nature du document
  n'en a pas (category = 1 ou 2 mots en français, sans accent : « Design »,
  « Voyages », « Animaux »), puis un sous-dossier au nom du projet, de la personne ou
  de l'organisme quand plusieurs fichiers le concerneront (« Design/Sarah-Mbossa »,
  « Factures/Stagio »). Indique folder_is_new = true. Un dossier dédié à un fichier
  unique et sans suite probable n'a pas lieu d'être : range-le dans la catégorie.
```

Quand elle ne l'est pas :

```text
- Ne crée aucun dossier (l'utilisateur ne l'autorise pas) : ni catégorie ni
  sous-dossier. Choisis le dossier existant le plus adapté parmi les candidats. Si
  aucun ne convient vraiment, propose quand même le moins mauvais avec une confiance
  inférieure à 0.5 et dis dans reasoning quel dossier il faudrait créer.
```

### 3.3 Bloc Professionnel (`{mode_rules}`)

```text
# Mode Professionnel (la convention d'une équipe)
- Le chemin suit le gabarit de structure de la convention (ex. {client}/{year}/
  {project}/{category}). client = un code de la liste des clients, ou null s'il est
  inconnu (dis-le dans reasoning). project = un projet de la liste « Projets
  existants » ; un nouveau projet seulement si le contenu le nomme sans ambiguïté
  (project_code + project_name au format de la convention).
- Catégorie : la nature du document selon les descriptions de la convention. Un
  brief reçu du client, une maquette de travail, un livrable final, une source
  achetée et une facture ne vont pas au même endroit même s'ils parlent du même
  projet.
- Les corrections et règles de l'utilisateur priment, sauf si elles contredisent la
  convention d'équipe : signale alors le conflit dans reasoning et suis la convention.
- Si rien ne permet de ranger (client inconnu, document personnel, hors des
  projets) : target_folder = "" et confidence < 0.3. Un humain choisira.
{creation_rule}
```

`{creation_rule}` : « Ne propose un nouveau dossier que s'il suit le gabarit ; indique alors folder_is_new = true. »
ou « Ne propose aucun nouveau dossier (l'utilisateur ne l'autorise pas) : candidats et projets existants seulement. »

### 3.4 Exemples (`{examples}`)

```text
Exemple A — contenu lisible, destination confirmée (Professionnel)
Fichier : scan0042.pdf, 38 Ko, Téléchargements. Contenu : « DEVIS n° D-2026-118 — Acme
Corporation — Campagne Noël 2026 (projet 2026-042) — impression 500 affiches abribus —
date 12/10/2026 ». Candidats : ACME/2026/2026-042_Campagne-Noel/06_Admin (devis,
factures du projet) ; …/01_Brief.
→ {"document_kind": "devis", "subject": "impression affiches, projet 2026-042 ACME",
   "document_date_source": "contenu", "evidence": ["en-tête DEVIS n° D-2026-118",
   "client Acme Corporation, projet 2026-042", "dossier 06_Admin contient déjà les devis"],
   "client": "ACME", "project_code": "2026-042", "project_name": "Campagne-Noel",
   "category": "06_Admin", "date": "2026-10-12", "description": "Devis impression affiches",
   "target_folder": "ACME/2026/2026-042_Campagne-Noel/06_Admin", "folder_is_new": false,
   "confidence": 0.95, "reasoning": "Devis daté du 12/10/2026 pour le projet 2026-042
   d'ACME ; les devis de ce projet sont déjà dans 06_Admin.", "alternatives": []}

Exemple B — image sans texte, nom générique (Particulier)
Fichier : IMG_3381.jpg, 2,3 Mo, Pictures, image jointe : une carte grise photographiée.
Arborescence : Vehicule — 2 — (Entretien). Candidats : Vehicule/Entretien ; Administratif.
→ {"document_kind": "carte grise photographiée", "subject": "véhicule de l'utilisateur",
   "document_date_source": "aucune", "evidence": ["image : certificat d'immatriculation",
   "aucun texte extrait", "dossier Vehicule existant"], "client": null, "project_code":
   null, "project_name": null, "category": "Vehicule", "date": null, "description":
   "Carte grise", "target_folder": "Vehicule", "folder_is_new": false, "confidence": 0.72,
   "reasoning": "L'image montre une carte grise ; le dossier Vehicule existe. Sans texte
   lisible, la date et le véhicule exact ne sont pas certains.", "alternatives": []}

Exemple C — série déposée ensemble, dossier dédié à créer (Particulier, création autorisée)
Fichier : Planche de logos Sarah Mbossa-2.png, 1,6 Mo. Image : grille de logos
« Sarah Mbossa – journaliste ». Déposés en même temps : « Planche de logos Sarah
Mbossa-1.png » → Design/Sarah-Mbossa. Appel lister_dossiers("") → Photos (0),
Etudes (7), startup (3 : Presentation-projet-Stagio…) ; aucun dossier Design ni
Graphisme.
→ {"document_kind": "planche de logos", "subject": "identité visuelle de Sarah Mbossa",
   "document_date_source": "aucune", "evidence": ["image : logos avec le nom Sarah
   Mbossa", "fichier -1 de la même série déjà proposé dans Design/Sarah-Mbossa",
   "startup concerne Stagio, pas cette personne", "lister_dossiers racine : pas de
   dossier Design existant"], "client": null, "project_code": null,
   "project_name": null, "category": "Design", "date": null, "description": "Logos Sarah
   Mbossa planche 2", "target_folder": "Design/Sarah-Mbossa", "folder_is_new": true,
   "confidence": 0.88, "reasoning": "Création graphique pour Sarah Mbossa, comme le
   fichier -1 de la série : même dossier dédié, à créer. Ce n'est ni une photo ni un
   document d'études.", "alternatives": []}
```

### 3.5 Message par fichier (`user`)

```text
## Dossiers candidats (chemin — description)
{candidate_folders}

## Projets existants                      (Professionnel seulement)
{project_folders}

## Fichiers déjà rangés qui ressemblent à celui-ci
{similar_files}                           (modèle de nom | mot distinctif « … »)

## Déposés en même temps, déjà analysés (fichier → dossier proposé)
{dropped_together}

## Corrections passées semblables (fichier d'origine → choix final ; l'IA proposait …)
{correction_examples}

## Indice                                 (Professionnel seulement)
Client détecté automatiquement (peut être faux) : {client_hint}

## Fichier à ranger
Nom d'origine : {original_name}
Type : {extension} — {mime} — {size_human}
Dates du fichier (pas du document) : créé le {created}, modifié le {modified}
Dossier d'origine : {origin_folder}
Métadonnées : {metadata}
Contenu extrait ({n} caractères sur {total}) :
"""
{extracted_text}
"""
{image_note}
```

L'arborescence n'y figure pas : l'IA la lit avec `lister_dossiers` (§2.4).

Le **contexte de rangement** (fin du `system`, après les exemples) :

```text
# Contexte de rangement
## Convention de rangement            (ou « Convention d'équipe »)
Mode : Particulier | Professionnel
Structure : {structure_template}
Format des projets : {project_format}  (Professionnel)
Catégories : {categories_with_descriptions}
Clients (code : nom, alias) : {clients_list}   (Professionnel)
Nom des fichiers : {naming_template}   (pour que l'IA sache ce que le gabarit ajoute)

## Profil de l'utilisateur
{profile}

## Règles de cet utilisateur
{learned_rules}
```

---

## 4. Mesurer avant de remplacer

1. **Jeu d'essai Particulier** à créer (`sandbox-perso/`, 25 à 30 fichiers, `expected.csv`) : bulletins, factures
   (dont une d'un projet), attestations, CV, logos en série, page web d'un projet, photo de carte grise, capture
   d'écran, PDF scanné, deux fichiers du même modèle de nom, un document de 2024 téléchargé aujourd'hui.
2. `tribin eval sandbox/` (Professionnel, 42 fichiers) et `tribin eval sandbox-perso/`, deux passages chacun, p7 contre
   v2, même modèle (Mistral Medium), puis Haiku si clé disponible.
3. Métriques à suivre, en plus de « dossiers acceptables » : **calibration** (confiance moyenne des bonnes vs des
   mauvaises réponses, part des erreurs marquées « à vérifier »), **noms** (nom propre conservé ? date fausse ?),
   **tokens par fichier** et **part lue depuis le cache**.
4. Critère de bascule : au moins autant de dossiers acceptables, et moins d'erreurs à plus de 0,8 de confiance.
