"""Réglages de l'application : variables d'environnement, emplacements des données, garde-fou sandbox.

Aucun chemin, clé API ni nom de modèle n'est codé en dur ailleurs : tout passe par ce module.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_data_dir

APP_NAME = "TriBin"
KEYRING_SERVICE = "TriBin"

# Fournisseurs d'IA : variables d'environnement de la clé, nom dans le trousseau, modèle par défaut.
PROVIDERS: dict[str, dict] = {
    "anthropic": {"env": ("ANTHROPIC_API_KEY",), "keyring": "anthropic_api_key",
                  "default_model": "claude-haiku-5-5", "prefix": "claude"},
    "gemini": {"env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "keyring": "gemini_api_key",
               "default_model": "gemini-flash-latest", "prefix": "gemini"},
    "mistral": {"env": ("MISTRAL_API_KEY",), "keyring": "mistral_api_key",
                "default_model": "mistral-medium-latest",
                "prefix": ("mistral", "magistral", "ministral", "pixtral", "codestral", "devstral")},
}
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]["default_model"]

# Racine du dépôt quand l'appli tourne depuis les sources (src/tribin/config.py -> dépôt).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Dossiers spéciaux créés dans chaque racine.
STAGING_DIRNAME = "_TriBin"
STAGING_SUBDIR = "a_trier"
ARCHIVE_DIRNAME = "_Archive"


class SandboxViolation(PermissionError):
    """Opération refusée par le garde-fou de développement (TRIBIN_DEV_SANDBOX=1)."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "oui", "on"}


@dataclass(frozen=True)
class Settings:
    """Réglages résolus au démarrage."""

    dev_sandbox: bool
    sandbox_dir: Path
    data_dir: Path
    model: str
    user: str
    api_key: str | None = field(default=None, repr=False)
    provider: str = DEFAULT_PROVIDER

    @property
    def journal_dir(self) -> Path:
        return self.data_dir / "journal"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tribin.db"

    @property
    def profile_path(self) -> Path:
        return self.data_dir / "profile.md"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "tribin.log"

    def for_provider(self, provider: str, model: str | None = None) -> Settings:
        """Réglages pour un autre fournisseur (clé et modèle correspondants)."""
        if provider not in PROVIDERS:
            raise ValueError(f"Fournisseur d'IA inconnu : {provider} (possibles : {', '.join(PROVIDERS)})")
        key = self.api_key if provider == self.provider else read_api_key(provider)
        return replace(self, provider=provider, api_key=key, model=model_for(provider, model or self.model))

    def ensure_dirs(self) -> None:
        """Crée le dossier des données et du journal s'ils n'existent pas."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)


def model_for(provider: str, model: str | None) -> str:
    """Le modèle demandé s'il correspond au fournisseur, sinon le modèle par défaut de ce fournisseur."""
    info = PROVIDERS[provider]
    if model and model.lower().startswith(info["prefix"]):  # str ou tuple de préfixes
        return model
    return info["default_model"]


def read_api_key(provider: str = DEFAULT_PROVIDER) -> str | None:
    """Clé API du fournisseur : variable d'environnement (.env), sinon trousseau système."""
    info = PROVIDERS[provider]
    for name in info["env"]:
        key = os.environ.get(name, "").strip()
        if key:
            return key
    try:
        import keyring

        stored = keyring.get_password(KEYRING_SERVICE, info["keyring"])
        return stored or None
    except Exception:  # trousseau indisponible : pas bloquant
        return None


def is_packaged() -> bool:
    """Vrai pour l'application empaquetée (PyInstaller) : le garde-fou sandbox y est inactif par défaut."""
    return bool(getattr(sys, "frozen", False))


def load_settings(env_file: Path | None = None) -> Settings:
    """Lit le fichier .env (s'il existe) puis les variables d'environnement."""
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    sandbox_dir = Path(os.environ.get("TRIBIN_SANDBOX_DIR") or REPO_ROOT / "sandbox")
    data_dir = Path(os.environ.get("TRIBIN_DATA_DIR") or user_data_dir(APP_NAME, appauthor=False, roaming=True))
    try:
        default_user = getpass.getuser()
    except Exception:
        default_user = "utilisateur"
    provider = os.environ.get("TRIBIN_PROVIDER", "").strip().lower() or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER
    return Settings(
        dev_sandbox=_env_bool("TRIBIN_DEV_SANDBOX", default=not is_packaged()),
        sandbox_dir=sandbox_dir.resolve(),
        data_dir=data_dir,
        model=model_for(provider, os.environ.get("TRIBIN_MODEL", "").strip()),
        user=os.environ.get("TRIBIN_USER", "").strip() or default_user,
        api_key=read_api_key(provider),
        provider=provider,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Réglages mis en cache pour toute la durée du processus."""
    return load_settings()


def save_api_key(key: str, provider: str = DEFAULT_PROVIDER) -> None:
    """Enregistre la clé API du fournisseur dans le trousseau système."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, PROVIDERS[provider]["keyring"], key)


def is_within(path: Path, parent: Path) -> bool:
    """Vrai si `path` (résolu, liens suivis) est `parent` ou se trouve dessous."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def assert_in_sandbox(path: Path, settings: Settings | None = None) -> None:
    """Refuse tout chemin hors de la sandbox quand le garde-fou est actif.

    Le chemin est résolu (`..` et liens symboliques suivis) avant la comparaison.
    """
    settings = settings or get_settings()
    if not settings.dev_sandbox:
        return
    if not is_within(Path(path), settings.sandbox_dir):
        raise SandboxViolation(
            f"Mode développement : opération refusée hors de la sandbox ({settings.sandbox_dir}) : {path}"
        )


def setup_logging(settings: Settings | None = None, level: int = logging.INFO) -> None:
    """Configure le journal technique (tribin.log), distinct du journal des opérations."""
    settings = settings or get_settings()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("tribin")
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)
