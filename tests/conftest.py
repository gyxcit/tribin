"""Fixtures communes : réglages isolés dans un dossier temporaire, sandbox générée une fois par session."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tribin.config import Settings  # noqa: E402


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
