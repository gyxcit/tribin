from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fakes import oracle

from tribin.__main__ import main
from tribin.config import get_settings


@pytest.fixture
def env(tmp_path: Path, monkeypatch, sandbox_dir: Path) -> Path:
    sb = tmp_path / "sandbox"
    shutil.copytree(sandbox_dir, sb)
    monkeypatch.setenv("TRIBIN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRIBIN_SANDBOX_DIR", str(sb))
    monkeypatch.setenv("TRIBIN_DEV_SANDBOX", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    yield sb
    get_settings.cache_clear()


def test_help(capsys):
    assert main([]) == 0
    assert "propose" in capsys.readouterr().out


def test_propose_without_key_is_clear_error(env, capsys):
    code = main(["propose", str(env / "inbox" / "scan0042.pdf"), "--root", str(env / "root"),
                 "--convention", str(env / "convention.yaml")])
    assert code == 1 and "Clé API" in capsys.readouterr().out


def test_map_and_suggest_convention(env, capsys):
    out = env / "deduite.yaml"
    assert main(["map", str(env / "root"), "--convention", str(env / "convention.yaml"),
                 "--suggest-convention", str(out)]) == 0
    assert "Cartographie" in capsys.readouterr().out
    from tribin.db import Database
    from tribin.mapping.profiles import load_profiles

    rels = {p.rel for p in load_profiles(Database(get_settings().db_path), env / "root")}
    assert "ACME/2026/2026-042_Campagne-Noel/06_Admin" in rels
    assert not any("_PROJET_EN_COURS" in r for r in rels)
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["structure"]["template"] == "{client}/{year}/{project}/{category}"


def test_import_clients_with_backup(env, capsys):
    csv_file = env / "clients.csv"
    csv_file.write_text("code;nom;alias\nGARL;Garage Lefèvre;lefevre|garage lefevre\nACME;Acme;acme\n", encoding="utf-8")
    conv = env / "convention.yaml"
    assert main(["import-clients", str(csv_file), "--convention", str(conv)]) == 0
    data = yaml.safe_load(conv.read_text(encoding="utf-8"))
    codes = [c["code"] for c in data["clients"]]
    assert codes.count("ACME") == 1 and "GARL" in codes
    assert (env / "convention.yaml.bak").exists()
    assert "Déjà présents : ACME" in capsys.readouterr().out


def test_eval_command(env, monkeypatch, capsys, tmp_path):
    import tribin.cli.propose_cmd as pc

    monkeypatch.setattr(pc, "make_provider", lambda settings, model=None: oracle(env))
    monkeypatch.setattr(pc, "REPO_ROOT", tmp_path)
    assert main(["eval", str(env), "--min-score", "70"]) == 0
    out = capsys.readouterr().out
    assert "Dossiers exacts" in out and "100.0" in out
    assert list((tmp_path / "eval_results").glob("*.csv"))


def test_file_history_undo_create_structure(env, monkeypatch, capsys):
    import tribin.cli.propose_cmd as pc
    from fakes import fixed

    noel = "ACME/2026/2026-042_Campagne-Noel"
    monkeypatch.setattr(pc, "make_provider", lambda settings, model=None: fixed(
        target_folder=f"{noel}/06_Admin", date="2026-10-12", description="Devis impression", confidence=0.9))
    src = env / "inbox" / "scan0042.pdf"
    conv = env / "convention.yaml"
    assert main(["file", str(src), "--root", str(env / "root"), "--convention", str(conv), "--yes"]) == 0
    target = env / "root" / noel / "06_Admin" / "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    assert target.exists() and not src.exists()
    assert main(["history"]) == 0
    out = capsys.readouterr().out
    assert "move" in out and "100%" in out
    from tribin.safety.journal import Journal

    batch = next(op["batch_id"] for op in Journal(get_settings().journal_dir).operations() if op["action"] == "move")
    assert main(["undo", "--batch", batch, "--yes"]) == 0
    assert src.exists() and not target.exists()

    assert main(["create-structure", "--root", str(env / "root"), "--convention", str(conv), "--client", "VELOM",
                 "--year", "2027", "--project", "2027-001_Salon-Velo", "--yes"]) == 0
    assert (env / "root" / "VELOM" / "2027" / "2027-001_Salon-Velo" / "06_Admin").is_dir()


def test_file_refuses_outside_sandbox(env, monkeypatch, tmp_path, capsys):
    import tribin.cli.propose_cmd as pc
    from fakes import fixed

    monkeypatch.setattr(pc, "make_provider", lambda settings, model=None: fixed(target_folder="A", description="x"))
    real_root = tmp_path / "vrai"
    (real_root / "A").mkdir(parents=True)
    src = tmp_path / "vrai.pdf"
    src.write_text("x")
    code = main(["file", str(src), "--root", str(real_root), "--convention", str(env / "convention.yaml"), "--yes"])
    assert code == 1 and src.exists()


def test_eval_min_score_fails_below_target(env, monkeypatch, tmp_path):
    import tribin.cli.propose_cmd as pc
    from fakes import fixed

    monkeypatch.setattr(pc, "make_provider", lambda settings, model=None: fixed(target_folder="ACME", description="x"))
    monkeypatch.setattr(pc, "REPO_ROOT", tmp_path)
    assert main(["eval", str(env), "--min-score", "70"]) == 2
