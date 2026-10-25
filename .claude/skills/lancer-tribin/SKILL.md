---
name: lancer-tribin
description: Lancer, essayer, mesurer et arrêter TriBin depuis les sources (application de bureau PySide6, ligne de commande, jeux d'essai, évaluation, empaquetage) sans lire le code. À utiliser dès qu'on demande de lancer, démarrer, relancer, tester ou empaqueter l'application, de savoir où sont ses données, sa configuration ou ses journaux, ou de faire un essai propre sans toucher aux vrais fichiers.
---

# Lancer TriBin

TriBin est une application de bureau (PySide6) avec une ligne de commande. Tout se lance avec `uv` depuis la racine
du dépôt ; `uv sync` installe Python 3.12 et les dépendances. Il n'y a pas de serveur : rien à ouvrir dans un
navigateur.

## 1. Préparer

```bash
uv sync
```

- Clé d'IA : copier `.env.example` en `.env`, choisir `TRIBIN_PROVIDER` (`mistral`, `anthropic` ou `gemini`) et la clé
  (`MISTRAL_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). Dans l'application, Réglages › Intelligence artificielle
  range la clé dans le trousseau du système : une clé déjà saisie là est trouvée sans `.env`. Le fournisseur et le
  modèle choisis dans l'application priment sur `.env`.
- Jeux d'essai (jamais commités) : `uv run python scripts/make_sandbox.py` crée `sandbox/` (agence fictive,
  mode Professionnel, 42 fichiers à ranger dans `sandbox/inbox/`), `uv run python scripts/make_sandbox_perso.py` crée
  `sandbox-perso/` (papiers d'une personne, mode Particulier, 27 fichiers). Chacun contient `convention.yaml`,
  `root/` (déjà rangé), `inbox/` (à ranger) et `expected.csv`.

## 2. Lancer l'application de bureau

```bash
uv run python -m tribin.ui.app
```

- Premier lancement : l'assistant demande le mode (Particulier ou Professionnel), les dossiers à ranger, la
  convention et l'IA. `--onboarding` le refait sur une installation existante.
- Des chemins de fichiers en arguments sont déposés au lancement. Une seule instance tourne : un second lancement lui
  transmet ses fichiers et s'arrête.
- `--diagnostic` affiche un rapport d'installation (fournisseurs, clés, trousseau) sans ouvrir l'interface.
- Pour arrêter : menu de l'icône de la barre système › Quitter (fermer la fenêtre ne quitte pas).

### Garde-fou de développement : où l'application a le droit d'écrire

Depuis les sources, `TRIBIN_DEV_SANDBOX` vaut `1` : tout déplacement de fichier est refusé hors de
`TRIBIN_SANDBOX_DIR` (par défaut `./sandbox`). C'est voulu : on peut faire tourner l'application sur
`sandbox/root` sans risque pour les vrais dossiers.

- Essai sur une racine réelle (celle configurée par l'utilisateur) : lancer avec `TRIBIN_DEV_SANDBOX=0`. Ne le faire que
  si l'utilisateur le demande : les fichiers bougent pour de vrai (journalisé, annulable depuis l'Historique).
- L'application empaquetée (`dist/`) n'a pas ce garde-fou.

### Où sont les données

`TRIBIN_DATA_DIR` (par défaut le dossier de données de l'utilisateur, sous Windows `%AppData%\Roaming\TriBin`) contient
`tribin.db` (configuration de l'application, file d'attente, corrections, règles apprises, profils de dossiers),
`convention_personnel.yaml` ou `convention.yaml`, le profil, le journal des opérations et `tribin.log` (journal
technique, à lire en cas d'erreur). Pour un essai propre qui ne touche ni la configuration ni l'apprentissage de
l'utilisateur, donner un dossier temporaire :

```bash
TRIBIN_DATA_DIR=/chemin/temporaire uv run python -m tribin.ui.app
```

L'assistant de premier lancement s'ouvre alors ; choisir `sandbox/root` (ou `sandbox-perso/root`) comme dossier à
ranger, puis déposer des fichiers de `sandbox/inbox/`. Un essai sur le vrai dossier de l'utilisateur, avec ses règles
apprises et ses corrections, se fait sans `TRIBIN_DATA_DIR` et avec `TRIBIN_DEV_SANDBOX=0`.

## 3. Ligne de commande (sans interface)

`uv run tribin <commande>` (ou `uv run python -m tribin`). Aucune de ces commandes ne déplace un fichier, sauf
`file`, `create-structure` et `undo`, qui simulent d'abord.

| Commande | Rôle |
|---|---|
| `propose <fichier> --root <racine> --convention <yaml> [--json] [--prompt v2\|p7]` | une proposition, rien n'est déplacé |
| `propose-dir <dossier> --root <racine> --convention <yaml>` | propositions pour tout un dossier |
| `eval <jeu> [--model …] [--prompt v2\|p7] [-v] [--min-score 70]` | mesure sur un jeu d'essai, rapport dans `eval_results/` |
| `map <racine> --convention <yaml> [--describe]` | cartographie des dossiers existants |
| `file <fichier> --root <racine> --convention <yaml>` | proposer, simuler, ranger |
| `history`, `undo --batch <id>` | journal des opérations, annulation |

L'évaluation appelle la vraie IA avec la clé de l'utilisateur (quelques centimes par passage) : demander son accord
avant de lancer `eval`. Exemple complet : `uv run tribin eval sandbox-perso/ --model mistral-medium-latest -v`.
Pour comparer l'ancien prompt et le nouveau : un passage `--prompt p7`, un passage `--prompt v2`.

## 4. Vérifier

```bash
uv run pytest -q
```

Environ 350 tests, interface Qt comprise (hors écran), sans appel réseau ni clé. Ils génèrent leurs propres jeux
d'essai dans un dossier temporaire.

## 5. Empaqueter (seulement si on le demande)

```bash
uv sync --extra packaging && uv run python scripts/make_icons.py && uv run pyinstaller packaging/tribin.spec --noconfirm
```

Résultat : `dist/TriBin/TriBin.exe` (Windows) ou `dist/TriBin.app` (macOS). Ne pas reconstruire `dist/` sans que
l'utilisateur le demande : c'est long et c'est la version qu'il utilise.

## 6. À ne pas faire

- Lancer l'application sur la racine réelle de l'utilisateur avec `TRIBIN_DEV_SANDBOX=0` sans son accord.
- Lancer `eval` ou `propose` en boucle : chaque fichier coûte un appel d'IA.
- Commiter `sandbox/`, `sandbox-perso/`, `eval_results/`, `.env` ou `dist/` (ils sont ignorés par Git).
- Modifier `tribin.db` ou les conventions de l'utilisateur à la main pendant que l'application tourne.

## 7. Où lire ensuite

- `README.md` : parcours utilisateur, raccourcis, règles de sécurité.
- `SPEC.md` section 8 (prompt et outil de l'IA), section 10 (jeux d'essai et métriques), section 13 (journal des
  mesures).
- `docs/triage-skill-v2.md` : les consignes données à l'IA ; `docs/etat-modes-2026-10-26.md` : état par mode.
