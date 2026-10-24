"""Tests de l'interface en mode « offscreen » (sans écran). Sautés si PySide6 n'est pas installé."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from fakes import fixed  # noqa: E402
from PySide6.QtCore import QThreadPool  # noqa: E402

import tribin.ui.app as app_mod  # noqa: E402
from tribin.service.bin import BinService  # noqa: E402
from tribin.service.config_store import AppConfig  # noqa: E402

NOEL = "ACME/2026/2026-042_Campagne-Noel"


@pytest.fixture(scope="session")
def qapp():
    app = app_mod.TriBinApplication.instance() or app_mod.TriBinApplication(["tribin-test"])
    yield app
    QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()
    app.shutdown()  # libère Qt avant la fin de Python (évite un plantage à la fermeture sous Windows)


def dispose(qapp, *widgets) -> None:
    """Ferme et détruit les fenêtres créées par un test (destruction ordonnée, avant QApplication)."""
    for widget in widgets:
        widget.hide()
        widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def controller(qapp, settings, sandbox_dir, monkeypatch):
    sb = settings.sandbox_dir / "copy"
    shutil.copytree(sandbox_dir, sb)
    monkeypatch.setattr(app_mod, "is_being_written", lambda path, delay=2.0: False)
    llm = fixed(target_folder=f"{NOEL}/06_Admin", date="2026-10-12", description="Devis impression", confidence=0.9,
                reasoning="Devis de l'imprimeur")
    svc = BinService(settings, provider_factory=lambda s, m=None: llm)
    svc.update_config(AppConfig(roots=[str(sb / "root")], convention_path=str(sb / "convention.yaml"),
                                onboarding_done=True, privacy_accepted=True))
    c = app_mod.AppController(qapp, svc, show_ui=False)
    c.sb = sb
    c.extra = []
    yield c
    QThreadPool.globalInstance().waitForDone(10000)
    dispose(qapp, c.bin_window, c.drop_widget, c.tray, *c.extra)


def wait(qapp, condition, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_drop_shows_proposal_in_bin_window(qapp, controller):
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: controller.service.pending() and controller.service.pending()[0].status == "ready")
    controller.refresh_queue()
    table = controller.bin_window.table
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    assert "Devis de l'imprimeur" in table.item(0, 2).toolTip()
    assert "1 fichier" in controller.tray.toolTip()


def test_ui_stays_responsive_with_20_files(qapp, controller):
    inbox = controller.sb / "inbox"
    files = sorted(p for p in inbox.iterdir() if p.is_file())[:20]
    started = time.monotonic()
    controller.drop_paths(files)
    assert time.monotonic() - started < 0.5  # le fil de l'interface n'attend pas les analyses
    assert wait(qapp, lambda: len([i for i in controller.service.pending() if i.status == "ready"]) == 20, 60)


def test_validate_and_return_from_window(qapp, controller, monkeypatch):
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf", controller.sb / "inbox" / "BC_4512.pdf"])
    assert wait(qapp, lambda: len([i for i in controller.service.pending() if i.status == "ready"]) == 2)
    controller.refresh_queue()
    win = controller.bin_window
    # renvoyer le 2e fichier à l'origine
    win.table.selectRow(1)
    returned = controller.service.pending()[1]
    win.return_selected()
    assert wait(qapp, lambda: len(controller.service.pending()) == 1)
    assert Path(returned.original_path).exists()
    # modifier le nom puis valider
    controller.refresh_queue()
    win.table.selectRow(0)
    win.table.item(0, 2).setText("2026-10-12_ACME_2026-042_Devis-final.pdf")
    win.validate_selected()
    assert wait(qapp, lambda: not controller.service.pending())
    assert (controller.sb / "root" / NOEL / "06_Admin" / "2026-10-12_ACME_2026-042_Devis-final.pdf").exists()
    states = controller.service.executor().journal.states().values()
    assert any(s.get("decision") == "edited" and s["status"] == "done" for s in states)


def test_queue_restored_after_restart(qapp, controller, settings):
    controller.drop_paths([controller.sb / "inbox" / "notes.txt"])
    assert wait(qapp, lambda: controller.service.pending() and controller.service.pending()[0].status == "ready")
    other = app_mod.AppController(qapp, BinService(settings, provider_factory=controller.service._provider_factory),
                                  show_ui=False)
    other.refresh_queue()
    assert other.bin_window.table.rowCount() == 1
    controller.extra += [other.bin_window, other.drop_widget, other.tray]


def test_windows_are_constructible(qapp, controller):
    from tribin.ui.history import HistoryWindow
    from tribin.ui.onboarding import OnboardingWizard
    from tribin.ui.settings import SettingsDialog

    windows = [HistoryWindow(controller), SettingsDialog(controller), OnboardingWizard(controller)]
    controller.extra += windows
    assert windows[0].table.columnCount() == 6
    assert windows[1].roots.count() == 1
    assert windows[2].pageIds()


def test_bin_icon_badge(qapp):
    from tribin.ui.icons import bin_pixmap

    assert not bin_pixmap(32, 0).toImage() == bin_pixmap(32, 3).toImage()
