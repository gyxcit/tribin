from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from tribin.config import SandboxViolation, assert_in_sandbox, load_settings


def test_inside_sandbox_is_accepted(settings):
    target = settings.sandbox_dir / "root" / "fichier.pdf"
    assert_in_sandbox(target, settings)


def test_outside_sandbox_is_refused(settings, tmp_path):
    with pytest.raises(SandboxViolation):
        assert_in_sandbox(tmp_path / "ailleurs" / "fichier.pdf", settings)


def test_dotdot_escape_is_refused(settings):
    with pytest.raises(SandboxViolation):
        assert_in_sandbox(settings.sandbox_dir / "root" / ".." / ".." / "evasion.txt", settings)


def test_symlink_escape_is_refused(settings, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = settings.sandbox_dir / "lien"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("création de liens symboliques non autorisée sur ce système")
    with pytest.raises(SandboxViolation):
        assert_in_sandbox(link / "fichier.txt", settings)


def test_guard_disabled_accepts_anything(settings, tmp_path):
    assert_in_sandbox(tmp_path / "ailleurs.txt", replace(settings, dev_sandbox=False))


def test_load_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBIN_DEV_SANDBOX", "0")
    monkeypatch.setenv("TRIBIN_MODEL", "claude-modele-x")
    monkeypatch.setenv("TRIBIN_DATA_DIR", str(tmp_path / "d"))
    s = load_settings(env_file=tmp_path / "absent.env")
    assert s.dev_sandbox is False
    assert s.model == "claude-modele-x"
    assert s.journal_dir == Path(tmp_path / "d" / "journal")


def test_sandbox_guard_is_on_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIBIN_DEV_SANDBOX", raising=False)
    assert load_settings(env_file=tmp_path / "absent.env").dev_sandbox is True


def test_sandbox_guard_is_off_by_default_in_packaged_app(monkeypatch, tmp_path):
    import sys

    monkeypatch.delenv("TRIBIN_DEV_SANDBOX", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert load_settings(env_file=tmp_path / "absent.env").dev_sandbox is False
    monkeypatch.setenv("TRIBIN_DEV_SANDBOX", "1")  # toujours activable explicitement (test de fumée)
    assert load_settings(env_file=tmp_path / "absent.env").dev_sandbox is True
