"""Fixtures communes : réglages isolés dans un dossier temporaire, sandbox générée une fois par session."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tribin.config import Settings  # noqa: E402


ENV_VARS = ("TRIBIN_PROVIDER", "TRIBIN_MODEL", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY",
            "TRIBIN_DEV_SANDBOX", "TRIBIN_DATA_DIR", "TRIBIN_SANDBOX_DIR", "TRIBIN_USER")


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Les tests ne lisent ni le fichier .env du développeur, ni ses variables, ni son trousseau."""
    import tribin.config as cfg

    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cfg, "load_dotenv", lambda *a, **k: False)
    def env_only(provider: str = cfg.DEFAULT_PROVIDER):
        info = cfg.PROVIDERS[provider]
        return next((os.environ[n] for n in info["env"] if os.environ.get(n)), None)

    monkeypatch.setattr(cfg, "read_api_key", env_only)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Réglages de test : sandbox = tmp_path/sandbox, données = tmp_path/data, garde-fou actif."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    return Settings(
        dev_sandbox=True,
        sandbox_dir=sandbox.resolve(),
        data_dir=tmp_path / "data",
        model="test-model",
        user="testeur",
        api_key=None,
    )


@pytest.fixture(scope="session")
def sandbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Sandbox complète générée une seule fois (lecture seule pour les tests)."""
    from make_sandbox import make_sandbox

    dest = tmp_path_factory.mktemp("sb") / "sandbox"
    make_sandbox(dest)
    return dest
