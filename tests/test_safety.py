"""Tests OBLIGATOIRES de la phase 3 (section 9) : sécurité des fichiers, journal, restauration."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tribin.safety import restore
from tribin.safety.executor import LOCKED_MESSAGE, Choice, Executor

RESTORE_PY = Path(__file__).resolve().parents[1] / "src" / "tribin" / "safety" / "restore.py"


@pytest.fixture
def env(settings):
    root = settings.sandbox_dir / "root"
    inbox = settings.sandbox_dir / "inbox"
    (root / "ACME" / "06_Admin").mkdir(parents=True)
    (root / "ACME" / "_PROJET_EN_COURS").mkdir(parents=True)
    inbox.mkdir()
    ex = Executor([root], settings.journal_dir, ["**/_PROJET_EN_COURS/**"], settings=settings)
    return ex, root, inbox


def make(path: Path, content: str = "contenu") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run(ex: Executor, choices: list[Choice]):
    ops = ex.plan(choices)
    report = ex.simulate(ops)
    return report, ex.execute(ops)


# --- jamais d'écrasement ---------------------------------------------------------------------


def test_never_overwrites_even_if_only_case_differs(env):
    ex, root, inbox = env
    existing = make(root / "ACME" / "06_Admin" / "Devis.pdf", "ORIGINAL")
    src = make(inbox / "scan.pdf", "NOUVEAU")
    sim, result = run(ex, [Choice(src, root, "ACME/06_Admin", "devis.pdf")])
    assert sim.ok and any("existe déjà" in n for n in sim.operations[0].notes)
    assert result.done
    assert existing.read_text(encoding="utf-8") == "ORIGINAL"
    assert result.done[0].destination.name == "devis_2.pdf"
    assert (root / "ACME" / "06_Admin" / "devis_2.pdf").read_text(encoding="utf-8") == "NOUVEAU"


def test_collision_appearing_after_simulation_gets_suffix(env):
    ex, root, inbox = env
    src = make(inbox / "a.pdf", "NOUVEAU")
    ops = ex.plan([Choice(src, root, "ACME/06_Admin", "Facture.pdf")])
    assert ex.simulate(ops).ok
    intrus = make(root / "ACME" / "06_Admin" / "FACTURE.pdf", "INTRUS")  # apparu entre-temps
    result = ex.execute(ops)
    assert intrus.read_text(encoding="utf-8") == "INTRUS"
    assert result.done[0].destination.name == "Facture_2.pdf"


def test_two_files_same_name_in_batch(env):
    ex, root, inbox = env
    a, b = make(inbox / "a.pdf", "A"), make(inbox / "b.pdf", "B")
    _, result = run(ex, [Choice(a, root, "ACME/06_Admin", "Devis.pdf"), Choice(b, root, "ACME/06_Admin", "Devis.pdf")])
    names = sorted(op.destination.name for op in result.done)
    assert names == ["Devis.pdf", "Devis_2.pdf"]


def test_safe_move_refuses_existing_destination(tmp_path):
    a, b = make(tmp_path / "a.txt", "A"), make(tmp_path / "B.TXT", "B")
    with pytest.raises(FileExistsError):
        restore.safe_move(a, tmp_path / "b.txt")
    assert a.exists() and b.read_text() == "B"


# --- noms réservés et chemins trop longs -----------------------------------------------------


@pytest.mark.parametrize("name", ["CON.pdf", "nul", "COM3.txt", "LPT1.doc", "a:b.pdf", "fin."])
def test_reserved_or_invalid_names_refused(env, name):
    ex, root, inbox = env
    src = make(inbox / "x.pdf")
    sim, result = run(ex, [Choice(src, root, "ACME/06_Admin", name)])
    assert not sim.ok and result.failed and src.exists()


def test_too_long_path_refused(env):
    ex, root, inbox = env
    src = make(inbox / "x.pdf")
    long_name = "a" * (260 - len(str(root / "ACME" / "06_Admin"))) + ".pdf"
    sim, result = run(ex, [Choice(src, root, "ACME/06_Admin", long_name)])
    assert any("trop long" in p for p in sim.problems[sim.operations[0].operation_id])
    assert src.exists() and result.failed


# --- fichier verrouillé ----------------------------------------------------------------------


def test_locked_file_clear_error_and_nothing_lost(env, monkeypatch):
    ex, root, inbox = env
    src = make(inbox / "ouvert.docx", "DATA")

    def locked(a, b):
        raise PermissionError(32, "Le processus ne peut pas accéder au fichier")

    monkeypatch.setattr(restore.os, "rename", locked)
    _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "Doc.docx")])
    op = result.operations[-1]
    assert op.status == "failed" and op.error == LOCKED_MESSAGE
    assert src.read_text() == "DATA"
    assert not (root / "ACME" / "06_Admin" / "Doc.docx").exists()
    assert ex.journal.states()[op.operation_id]["status"] == "failed"


@pytest.mark.skipif(sys.platform != "win32", reason="verrouillage réel propre à Windows")
def test_really_locked_file_on_windows(env):
    ex, root, inbox = env
    src = make(inbox / "ouvert.xlsx", "DATA")
    with open(src, "rb"):
        _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "Tableau.xlsx")])
    assert result.operations[-1].error == LOCKED_MESSAGE and src.exists()


# --- périmètre : racine, zones exclues, .., liens symboliques ---------------------------------


def test_outside_root_refused(env):
    ex, root, inbox = env
    src = make(inbox / "x.pdf")
    for folder in ("../evasion", "ACME/../../evasion"):
        sim, result = run(ex, [Choice(src, root, folder, "x.pdf")])
        assert not sim.ok and result.failed and src.exists()


def test_excluded_zone_refused(env):
    ex, root, inbox = env
    src = make(inbox / "x.pdf")
    sim, result = run(ex, [Choice(src, root, "ACME/_PROJET_EN_COURS", "x.pdf")])
    assert not sim.ok and result.failed and src.exists()
    assert not any((root / "ACME" / "_PROJET_EN_COURS").iterdir())


def test_moving_out_of_excluded_zone_refused(env):
    ex, root, _ = env
    src = make(root / "ACME" / "_PROJET_EN_COURS" / "lie.indd")
    sim, _ = run(ex, [Choice(src, root, "ACME/06_Admin", "lie.indd")])
    assert not sim.ok and src.exists()


def test_symlink_escape_refused(env, tmp_path):
    ex, root, inbox = env
    outside = tmp_path / "dehors"
    outside.mkdir()
    try:
        os.symlink(outside, root / "ACME" / "lien", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques non autorisés")
    src = make(inbox / "x.pdf")
    sim, result = run(ex, [Choice(src, root, "ACME/lien", "x.pdf")])
    assert not sim.ok and result.failed and not any(outside.iterdir())


# --- déplacement inter-volumes ---------------------------------------------------------------


def test_cross_volume_interrupted_after_copy(env, monkeypatch):
    ex, root, inbox = env
    monkeypatch.setattr(restore, "same_volume", lambda a, b: False)
    src = make(inbox / "video.mp4", "X" * 5000)

    def crash(partial: Path):
        assert partial.name.endswith(".tribin-partial") and partial.exists()
        raise RuntimeError("coupure réseau simulée")

    ex._after_copy = crash
    _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "Video.mp4")])
    assert result.operations[-1].status == "failed"
    assert src.read_text() == "X" * 5000
    assert list((root / "ACME" / "06_Admin").iterdir()) == []  # ni fichier final, ni fichier partiel


def test_cross_volume_success_records_hashes(env, monkeypatch):
    ex, root, inbox = env
    monkeypatch.setattr(restore, "same_volume", lambda a, b: False)
    src = make(inbox / "video.mp4", "Y" * 3000)
    _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "Video.mp4")])
    op = result.done[-1]
    assert not src.exists() and op.destination.exists()
    rec = ex.journal.states()[op.operation_id]
    assert rec["hash_after"] == rec["hash_before"] and rec["hash_after"].startswith("sha256:")


# --- journal ----------------------------------------------------------------------------------


def test_journal_written_before_execution(env, monkeypatch):
    ex, root, inbox = env
    src = make(inbox / "x.pdf")
    ops = ex.plan([Choice(src, root, "ACME/06_Admin", "X.pdf")])
    seen = []
    real_move = restore.safe_move

    def spy(a, b, after_copy=None):
        seen.append(ex.journal.states()[ops[-1].operation_id]["status"])
        return real_move(a, b, after_copy)

    monkeypatch.setattr(restore, "safe_move", spy)
    ex.execute(ops)
    assert seen == ["pending"]
    assert ex.journal.states()[ops[-1].operation_id]["status"] == "done"


def test_simulation_touches_nothing(env):
    ex, root, inbox = env
    src = make(inbox / "x.pdf")
    ops = ex.plan([Choice(src, root, "CLIENT/2026/Projet/06_Admin", "X.pdf")])
    report = ex.simulate(ops)
    assert report.ok and src.exists() and not (root / "CLIENT").exists()
    assert {s["status"] for s in ex.journal.states().values()} == {"simulated"}


def test_corrupted_last_line_ignored(tmp_path):
    restore.append_record(tmp_path, {"operation_id": "op_1", "action": "move", "status": "done"})
    with open(restore.journal_file(tmp_path), "a", encoding="utf-8") as fh:
        fh.write('{"operation_id": "op_2", "act')
    assert [r["operation_id"] for r in restore.read_records(tmp_path)] == ["op_1"]


# --- restauration -----------------------------------------------------------------------------


def test_restore_batch_of_20_with_one_moved_meanwhile(env, settings):
    ex, root, inbox = env
    sources = [make(inbox / f"fichier_{i:02d}.pdf", f"contenu {i}") for i in range(20)]
    _, result = run(ex, [Choice(s, root, f"CLIENT/Projet_{i % 3}", f"Range_{i:02d}.pdf") for i, s in enumerate(sources)])
    assert len([o for o in result.done if o.action == "move"]) == 20
    moved_away = result.done[-1].destination
    os.rename(moved_away, inbox / "deplace_a_la_main.pdf")

    preview = ex.undo(batch_id=result.batch_id, execute=False)
    assert all(r["status"] in {"would_undo", "ignored"} for r in preview) and not sources[0].exists()

    results = ex.undo(batch_id=result.batch_id)
    undone_files = [r for r in results if r["status"] == "undone" and r["action"] == "move"]
    ignored = [r for r in results if r["status"] == "ignored" and r["action"] == "move"]
    assert len(undone_files) == 19 and len(ignored) == 1 and "déplacé" in ignored[0]["message"]
    assert all(s.exists() for s in sources[:19]) and not sources[19].exists()
    for i, s in enumerate(sources[:19]):
        assert s.read_text() == f"contenu {i}"
    # dossiers créés par le lot : retirés seulement s'ils sont vides
    assert not (root / "CLIENT" / "Projet_2").exists() or any((root / "CLIENT" / "Projet_2").iterdir())
    states = ex.journal.states()
    assert any(s["action"] == "undo" and s["status"] == "done" for s in states.values())


def test_restore_never_overwrites_origin(env):
    ex, root, inbox = env
    src = make(inbox / "Devis.pdf", "RANGE")
    _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "Devis.pdf")])
    make(inbox / "Devis.pdf", "NOUVEAU A LA MEME PLACE")
    results = ex.undo(batch_id=result.batch_id)
    assert results[0]["status"] == "undone"
    assert (inbox / "Devis.pdf").read_text() == "NOUVEAU A LA MEME PLACE"
    assert (inbox / "Devis_restaure.pdf").read_text() == "RANGE"


def test_restore_skips_modified_file(env):
    ex, root, inbox = env
    src = make(inbox / "a.pdf", "v1")
    _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "A.pdf")])
    (root / "ACME" / "06_Admin" / "A.pdf").write_text("v2 modifiée")
    results = ex.undo(batch_id=result.batch_id)
    assert results[0]["status"] == "ignored" and not src.exists()


def test_restore_script_runs_standalone(env, settings):
    ex, root, inbox = env
    src = make(inbox / "a.pdf", "A")
    _, result = run(ex, [Choice(src, root, "ACME/06_Admin", "A.pdf")])
    cmd = [sys.executable, "-I", str(RESTORE_PY), "--journal", str(settings.journal_dir), "--batch", result.batch_id]
    sim = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert sim.returncode == 0 and "Simulation" in sim.stdout and not src.exists()
    done = subprocess.run([*cmd, "--execute"], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    assert src.read_text() == "A"
    listing = subprocess.run([sys.executable, "-I", str(RESTORE_PY), "--journal", str(settings.journal_dir), "--list"],
                             capture_output=True, text=True, encoding="utf-8")
    assert result.batch_id in listing.stdout


def test_restore_imports_only_stdlib():
    tree = ast.parse(RESTORE_PY.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "import relatif interdit dans restore.py"
            modules.add(node.module.split(".")[0])
    assert modules - {"__future__"} <= set(sys.stdlib_module_names), modules - set(sys.stdlib_module_names)


# --- garde-fou sandbox ------------------------------------------------------------------------


def test_sandbox_guard_refuses_outside(settings, tmp_path):
    outside_root = tmp_path / "vrai_dossier"
    (outside_root / "A").mkdir(parents=True)
    src = make(tmp_path / "vrai_fichier.pdf", "PRECIEUX")
    ex = Executor([outside_root], settings.journal_dir, settings=settings)
    sim, result = run(ex, [Choice(src, outside_root, "A", "x.pdf")])
    assert not sim.ok and "sandbox" in " ".join(sim.problems[sim.operations[0].operation_id])
    assert result.failed and src.read_text() == "PRECIEUX"


def test_guard_disabled_allows_real_roots(settings, tmp_path):
    root = tmp_path / "racine"
    (root / "A").mkdir(parents=True)
    src = make(root / "x.pdf")
    ex = Executor([root], settings.journal_dir, settings=replace(settings, dev_sandbox=False))
    _, result = run(ex, [Choice(src, root, "A", "x.pdf")])
    assert result.done


def test_mkdir_undo_only_if_empty(env):
    ex, root, _ = env
    batch = ex.batch()
    batch.mkdirs(root, "NOUVEAU/Sous")
    assert ex.simulate(batch.ops).ok
    result = ex.execute(batch.ops)
    make(root / "NOUVEAU" / "ajout_manuel.txt")
    results = {r["to"] or r["from"]: r["status"] for r in ex.undo(batch_id=result.batch_id)}
    assert not (root / "NOUVEAU" / "Sous").exists()
    assert (root / "NOUVEAU" / "ajout_manuel.txt").exists()
    assert "ignored" in results.values()


def test_journal_lines_are_json(env, settings):
    ex, root, inbox = env
    run(ex, [Choice(make(inbox / "a.pdf"), root, "ACME/06_Admin", "A.pdf")])
    for path in settings.journal_dir.glob("journal-*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            assert {"ts", "operation_id", "batch_id", "action", "status", "user", "app_version"} <= rec.keys()


def test_undo_order_follows_journal_even_with_identical_timestamps(env, monkeypatch):
    ex, root, inbox = env
    monkeypatch.setattr(restore, "now_iso", lambda: "2026-10-24T10:00:00.000+02:00")  # même milliseconde partout
    src = make(inbox / "a.pdf")
    _, result = run(ex, [Choice(src, root, "NOUVEAU/Dossier", "A.pdf")])
    results = ex.undo(batch_id=result.batch_id)
    assert [r["action"] for r in results] == ["move", "mkdir", "mkdir"]
    assert all(r["status"] == "undone" for r in results)
    assert src.exists() and not (root / "NOUVEAU").exists()
