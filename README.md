# TriBin

Corbeille intelligente pour agences : on glisse un fichier, l'IA propose **où le ranger** et **comment le renommer**
selon la convention de l'équipe ; l'utilisateur valide ou corrige. Spécification complète : [SPEC.md](SPEC.md).

## Installation (développement)

Prérequis : [uv](https://docs.astral.sh/uv/) (il installe Python 3.12 si besoin).

```bash
uv sync
cp .env.example .env   # puis renseigner ANTHROPIC_API_KEY
uv run python scripts/make_sandbox.py
uv run pytest
```

## Emplacement des données et du journal (à retrouver en urgence)

| Système | Dossier des données |
|---------|---------------------|
| macOS   | `~/Library/Application Support/TriBin/` |
| Windows | `%APPDATA%\TriBin\` |

Variable `TRIBIN_DATA_DIR` pour le changer.
