"""Tests de l'interface en mode « offscreen » (sans écran). Sautés si PySide6 n'est pas installé."""

from __future__ import annotations

import os
import sys
import shutil
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from fakes import fixed  # noqa: E402
from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton  # noqa: E402

import tribin.ui.app as app_mod  # noqa: E402
from tribin.service.bin import BinService  # noqa: E402
from tribin.service.config_store import AppConfig  # noqa: E402

NOEL = "ACME/2026/2026-042_Campagne-Noel"


@pytest.fixture(scope="session")
def qapp():
    from tribin.ui.theme import apply_theme

    app = app_mod.TriBinApplication.instance() or app_mod.TriBinApplication(["tribin-test"])
    apply_theme(app)
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


def ready_items(controller, n: int) -> bool:
    return len([i for i in controller.service.pending() if i.status == "ready"]) == n


def test_drop_shows_proposal_in_bin_window(qapp, controller):
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 1))
    controller.refresh_queue()
    win = controller.bin_window
    item = controller.service.pending()[0]
    assert win.queue.order == [item.file_id] and win.bin_pages.currentIndex() == 1
    assert win.detail.name.text() == "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    assert win.detail.folder == f"{NOEL}/06_Admin"
    assert "Devis de l'imprimeur" in win.detail.reasoning.text()
    assert win.detail.pill.text() == "Sûr · 90 %"
    assert win.detail.original.text() == "scan0042.pdf"
    assert "1 fichier" in controller.tray.toolTip() and win.pending_count.text() == "1"


def test_ui_stays_responsive_with_20_files(qapp, controller):
    inbox = controller.sb / "inbox"
    files = sorted(p for p in inbox.iterdir() if p.is_file())[:20]
    started = time.monotonic()
    controller.drop_paths(files)
    assert time.monotonic() - started < 0.5  # le fil de l'interface n'attend pas les analyses
    assert wait(qapp, lambda: ready_items(controller, 20), 60)


def test_validate_and_return_from_window(qapp, controller):
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf", controller.sb / "inbox" / "BC_4512.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 2))
    controller.refresh_queue()
    win = controller.bin_window
    first, returned = controller.service.pending()
    win.select_file(returned.file_id)
    win.return_selected()
    assert wait(qapp, lambda: len(controller.service.pending()) == 1)
    assert Path(returned.original_path).exists()
    controller.refresh_queue()
    win.select_file(first.file_id)
    win.detail.name.setText("2026-10-12_ACME_2026-042_Devis-final.pdf")
    win.validate_selected()
    assert wait(qapp, lambda: not controller.service.pending())
    assert (controller.sb / "root" / NOEL / "06_Admin" / "2026-10-12_ACME_2026-042_Devis-final.pdf").exists()
    states = controller.service.executor().journal.states().values()
    assert any(s.get("decision") == "edited" and s["status"] == "done" for s in states)


def test_category_in_one_click(qapp, controller):
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 1))
    controller.refresh_queue()
    win = controller.bin_window
    combo = win.detail.category
    codes = [combo.itemData(i) for i in range(combo.count())]
    assert codes == ["01_Brief", "02_Creation", "03_Execution", "04_Livrables", "05_Sources", "06_Admin"]
    assert combo.currentData() == "06_Admin" and combo.isEnabled()
    combo.activated.emit(codes.index("01_Brief"))
    assert win.detail.folder == f"{NOEL}/01_Brief"
    validation = win._validation(win.current_item())
    assert validation.target_folder == f"{NOEL}/01_Brief" and validation.decision == "edited"


def test_queue_restored_after_restart(qapp, controller, settings):
    controller.drop_paths([controller.sb / "inbox" / "notes.txt"])
    assert wait(qapp, lambda: ready_items(controller, 1))
    other = app_mod.AppController(qapp, BinService(settings, provider_factory=controller.service._provider_factory),
                                  show_ui=False)
    other.refresh_queue()
    assert len(other.bin_window.queue.order) == 1
    controller.extra += [other.bin_window, other.drop_widget, other.tray]


def test_batch_shows_simulation_then_history_and_undo(qapp, controller, monkeypatch):
    from tribin.ui.simulation_dialog import SimulationDialog

    shown = []

    def confirm(report) -> bool:
        shown.append(SimulationDialog(report))
        return True

    controller.confirm_simulation = confirm
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf", controller.sb / "inbox" / "BC_4512.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 2))
    controller.refresh_queue()
    controller.bin_window.validate_all()
    assert wait(qapp, lambda: not controller.service.pending())
    controller.extra += shown
    assert shown and shown[0].confirm.isEnabled() and shown[0].confirm.text() == "Ranger 2 fichiers"

    history = controller.bin_window.history
    controller.bin_window.show_page("history")
    labels = [w.text() for w in history.findChildren(QLabel)]
    assert any("2 fichiers rangés" in t for t in labels)
    assert any("Proposition de l'IA acceptée telle quelle" in t for t in labels)  # détail d'un fichier
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    undo = next(b for b in history.findChildren(QPushButton) if "Annuler le lot" in b.text())
    undo.click()
    placed = controller.sb / "root" / NOEL / "06_Admin" / "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    assert not placed.exists()
    assert any(w.text() == "Annulé" for w in history.findChildren(QLabel))


def test_simulation_dialog_blocks_on_problem(qapp, controller):
    from tribin.safety.executor import SimulationReport
    from tribin.safety.operations import Operation
    from tribin.ui.simulation_dialog import SimulationDialog

    root = controller.sb / "root"
    op = Operation("move", root / "CON.pdf", root, source=controller.sb / "inbox" / "scan0042.pdf")
    report = SimulationReport("b_test", [op], {op.operation_id: ["Nom invalide sous Windows ou macOS : « CON.pdf »"]})
    dialog = SimulationDialog(report)
    controller.extra.append(dialog)
    assert not dialog.confirm.isEnabled()


def test_drop_widget_states(qapp, controller):
    widget = controller.drop_widget
    widget.set_state(total=0)
    assert widget.stack.currentWidget() is widget.idle
    widget.set_state(total=3, analyzing=2)
    assert widget.stack.currentWidget() is widget.busy and widget.busy_count.text() == "1 / 3"
    widget.set_state(total=7, ready=5, check=2)
    assert widget.stack.currentWidget() is widget.ready_card
    assert widget.ready_title.text() == "7 à valider" and widget.check_pill.text() == "2 à vérifier"


def test_windows_are_constructible(qapp, controller):
    from tribin.ui.onboarding import OnboardingWizard
    from tribin.ui.settings import SettingsDialog

    controller.bin_window.history.reload()
    windows = [SettingsDialog(controller), OnboardingWizard(controller)]
    controller.extra += windows
    assert len(windows[0].roots.values()) == 1
    assert windows[1].pageIds()


def test_logo_and_badge(qapp):
    from tribin.ui.icons import LOGO_SVG, app_icon, logo_pixmap

    assert LOGO_SVG.exists()
    plain = logo_pixmap(32, 0).toImage()
    assert plain.pixelColor(16, 16).alpha() == 255  # le logo est bien dessiné (pas une image vide)
    assert plain != logo_pixmap(32, 3).toImage()  # la pastille change l'icône
    assert not app_icon(5).isNull()


def test_empty_state_edits_and_search(qapp, controller):
    win = controller.bin_window
    controller.refresh_queue()
    assert win.bin_pages.currentIndex() == 0  # écran « Tout est rangé »
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf", controller.sb / "inbox" / "BC_4512.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 2))
    controller.refresh_queue()
    by_name = {Path(i.original_path).name: i for i in controller.service.pending()}
    first, second = by_name["scan0042.pdf"], by_name["BC_4512.pdf"]
    win.select_file(first.file_id)
    win.detail.name.setText("modifie.pdf")
    win.select_file(second.file_id)
    controller.refresh_queue()  # une analyse qui se termine rafraîchit la liste
    win.select_file(first.file_id)
    assert win.detail.name.text() == "modifie.pdf"  # la modification n'est pas perdue
    assert win.queue.validate_all.label.text() == "Ranger les 2 prêts"
    win.queue.search.setText("BC_")
    assert win.queue.order == [second.file_id]  # la recherche filtre la file
    win.queue.search.clear()
    win.queue.set_tab("check")
    assert win.queue.order == []  # les deux fichiers sont prêts : rien à vérifier
    win.select_file(first.file_id)  # sélectionner un fichier masqué revient à « Tous »
    assert win.queue.tab == "all" and win.queue.current_file_id() == first.file_id


def test_onboarding_simple_flow(qapp, controller, monkeypatch):
    import tribin.ui.onboarding as onboarding

    saved_keys = []
    monkeypatch.setattr(onboarding, "save_api_key", lambda key, provider: saved_keys.append((provider, key)))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    wizard = onboarding.OnboardingWizard(controller)
    controller.extra.append(wizard)
    assert len(wizard.pageIds()) == 5
    secteur = wizard.chips["secteur"]
    agence, studio = secteur.group.buttons()[:2]
    agence.click()
    studio.click()
    assert secteur.value() == "Studio créatif"  # un seul choix à la fois
    wizard.chips["types"].group.buttons()[0].click()
    wizard.chips["types"].group.buttons()[1].click()
    assert wizard.chips["types"].value() == ["Visuels", "Documents"]
    wizard.set_provider("gemini")
    assert wizard.provider() == "gemini" and "aistudio.google.com" in wizard.api_key.hint.text()
    wizard.provider_cards["mistral"].mousePressEvent(None)  # un clic sur la carte la sélectionne
    wizard.api_key.setText("cle-de-test")
    wizard.accept()
    cfg = controller.service.config
    assert cfg.onboarding_done and cfg.provider == "mistral"
    assert saved_keys == [("mistral", "cle-de-test")]
    assert controller.service.ai_settings().api_key == "cle-de-test"
    conv = Path(cfg.convention_path)
    assert conv.exists() and conv.parent == controller.service.settings.data_dir  # déduite des dossiers


def test_folder_picker_one_by_one(qapp, tmp_path):
    from tribin.ui.folder_picker import FolderPicker, excluded_label, excluded_picker, excluded_value

    root = tmp_path / "Equipe"
    (root / "ACME" / "_PROJET").mkdir(parents=True)
    picker = FolderPicker([], "Ajouter un dossier", "Ajouter un autre dossier")
    assert picker.add_button.text().endswith("Ajouter un dossier")
    picker.add_value(str(root))
    picker.add_value(str(root))  # pas de doublon
    assert picker.values() == [str(root)]
    assert picker.add_button.text().endswith("Ajouter un autre dossier")

    assert excluded_value(root / "ACME" / "_PROJET", [str(root)]) == "ACME/_PROJET/**"
    with pytest.raises(ValueError):
        excluded_value(root, [str(root)])
    with pytest.raises(ValueError):
        excluded_value(tmp_path, [str(root)])
    assert excluded_label("ACME/_PROJET/**") == "ACME/_PROJET"
    assert excluded_label("**/_PROJET_EN_COURS/**") == "Tous les dossiers nommés « _PROJET_EN_COURS »"

    excluded = excluded_picker(["ACME/_PROJET/**"], picker.values)
    remove = next(b for b in excluded.findChildren(QPushButton) if b.text() == "Retirer")
    remove.click()
    assert excluded.values() == []


def test_auto_mode_and_widget_button(qapp, controller):
    widget = controller.drop_widget
    widget.set_state(total=3, ready=2, check=1)
    assert widget.auto_button.isVisibleTo(widget) and widget.auto_button.text() == "Ranger les 2 prêts"
    widget.set_state(total=1, check=1)
    assert not widget.auto_button.isVisibleTo(widget)

    cfg = controller.service.config
    cfg.auto_file = True
    controller.service.update_config(cfg)
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    placed = controller.sb / "root" / NOEL / "06_Admin" / "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    assert wait(qapp, placed.exists)  # confiance 0,9 : rangé sans aucun clic
    assert wait(qapp, lambda: not controller.service.pending())
    assert wait(qapp, lambda: not controller._notice_timer.isActive() and controller._notice["done"] == 0, 5)


def test_api_key_field_shows_saved_key_clearly(qapp):
    from tribin.ui.components import ApiKeyField

    field = ApiKeyField()
    field.set_provider("Mistral", "console.mistral.ai", "sk-1234567890abcdWXYZ")
    assert field.status.isVisibleTo(field) and not field.editor.isVisibleTo(field)
    assert "enregistrée" in field.status_title.text() and "••••WXYZ" in field.status_detail.text()
    assert "1234" not in field.status_detail.text()  # la clé n'est jamais affichée en entier
    field.replace_button.click()
    assert field.editor.isVisibleTo(field) and not field.status.isVisibleTo(field)
    field.setText("nouvelle")
    assert field.text() == "nouvelle"
    field.cancel.click()  # « Garder l'ancienne »
    assert field.text() == "" and field.status.isVisibleTo(field)
    field.set_provider("Gemini", "aistudio.google.com", None)
    assert field.editor.isVisibleTo(field) and not field.status.isVisibleTo(field)
    assert "aistudio.google.com" in field.hint.text()


def test_refresh_button_and_reanalyze(qapp, controller):
    from tribin.llm.base import LLMError

    svc = controller.service
    working = svc._provider_factory

    def no_key(settings, model=None):
        raise LLMError("Clé API manquante")

    svc._provider_factory = no_key
    svc.reload()
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: any(i.status == "ready" and i.proposal and i.proposal.manual for i in svc.pending()))

    svc._provider_factory = working  # la clé vient d'être ajoutée
    controller.refresh_queue()
    controller.bin_window.queue.refresh_button.click()
    assert wait(qapp, lambda: ready_items(controller, 1) and not svc.pending()[0].proposal.manual)
    assert "Actualisé" in controller.bin_window.statusBar().currentMessage()

    controller.refresh_queue()
    win = controller.bin_window
    win.select_file(svc.pending()[0].file_id)
    win.detail.reanalyze_button.click()
    assert wait(qapp, lambda: ready_items(controller, 1) and svc.pending()[0].proposal is not None)


def test_startup_retries_files_left_without_ai(qapp, controller):
    from tribin.llm.base import LLMError

    svc = controller.service
    working = svc._provider_factory

    def missing_module(settings, model=None):
        raise LLMError("Le module Mistral est absent")

    svc._provider_factory = missing_module
    svc.reload()
    item = svc.analyze(svc.drop(controller.sb / "inbox" / "scan0042.pdf").file_id)
    assert item.proposal.manual
    svc._provider_factory = working  # nouvelle version de l'appli, module présent
    svc.reload()
    controller.start([])
    assert wait(qapp, lambda: ready_items(controller, 1) and not svc.pending()[0].proposal.manual)


def test_widget_stays_on_screen_and_no_folder_means_no_ranging(qapp, controller):
    widget = controller.drop_widget
    widget.show()
    area = widget.screen().availableGeometry()
    widget.move(area.right() - 20, area.bottom() - 20)
    widget.set_state(total=3, ready=2, check=1)
    assert widget.geometry().right() <= area.right() and widget.geometry().bottom() <= area.bottom()
    widget.hide()

    from tribin.llm.base import LLMError

    def no_key(settings, model=None):
        raise LLMError("Clé API manquante")

    controller.service._provider_factory = no_key
    controller.service.reload()
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: any(i.status == "ready" for i in controller.service.pending()))
    controller.refresh_queue()
    detail = controller.bin_window.detail
    assert detail.folder == "" and not detail.validate_button.isEnabled()
    detail.set_folder(f"{NOEL}/06_Admin")  # dossier choisi à la main
    assert detail.validate_button.isEnabled()


def test_set_aside_button(qapp, controller):
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 1))
    controller.refresh_queue()
    win = controller.bin_window
    item = controller.service.pending()[0]
    win.select_file(item.file_id)
    assert win.detail.skip_button.label.text() == "Mettre de côté"
    win.detail.skip_button.click()  # un seul fichier : il quitte quand même la liste
    assert controller.service.pending() == [] and win.bin_pages.currentIndex() == 1
    assert win.queue.tab == "aside" and win.queue.order == [item.file_id]
    assert controller.drop_widget.counts["total"] == 0  # plus compté dans le widget
    win.select_file(item.file_id)
    assert win.detail.skip_button.label.text() == "Remettre à ranger"
    win.detail.skip_button.click()
    assert [i.file_id for i in controller.service.pending()] == [item.file_id]
    assert not win.queue.tab_buttons["aside"].isVisibleTo(win.queue)


def test_manual_edits_survive_restart_and_no_duplicate_message(qapp, controller, settings):
    from tribin.llm.base import LLMError

    def no_key(settings, model=None):
        raise LLMError("Clé API manquante")

    controller.service._provider_factory = no_key
    controller.service.reload()
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: any(i.status == "ready" for i in controller.service.pending()))
    controller.refresh_queue()
    win = controller.bin_window
    assert not win.detail.warnings.isVisibleTo(win.detail)  # la raison n'est pas répétée en avertissement
    win.detail.set_folder(f"{NOEL}/06_Admin")
    win.detail.name.setText("devis.pdf")
    item = controller.service.pending()[0]
    other = app_mod.AppController(qapp, BinService(settings, provider_factory=no_key), show_ui=False)
    controller.extra += [other.bin_window, other.drop_widget, other.tray]
    other.refresh_queue()
    other.bin_window.select_file(item.file_id)
    assert other.bin_window.detail.folder == f"{NOEL}/06_Admin"
    assert other.bin_window.detail.name.text() == "devis.pdf"


def test_personal_mode_in_onboarding_and_settings(qapp, controller, monkeypatch):
    from tribin.ui import onboarding
    from tribin.ui.settings import SettingsDialog

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(onboarding, "save_api_key", lambda key, provider: None)
    wizard = onboarding.OnboardingWizard(controller)
    controller.extra.append(wizard)
    assert wizard.mode() == "work"  # convention d'agence de la sandbox
    wizard.set_mode("personal")
    ids = wizard.pageIds()
    wizard.setStartId(ids[2])
    wizard.restart()
    assert wizard.nextId() == ids[4]  # « Votre activité » sautée en mode personnel
    assert not wizard.convention_box.isVisibleTo(wizard)
    wizard.accept()
    conv = controller.service.convention()
    assert conv.personal and "Salaires" in conv.category_codes() and "ACME" in conv.category_codes()

    dialog = SettingsDialog(controller)
    controller.extra.append(dialog)
    assert dialog.mode() == "personal"
    dialog.mode_cards["work"].radio.setChecked(True)
    dialog._save()
    assert not controller.service.convention().personal


def test_history_reveal_button(qapp, controller, monkeypatch):
    import tribin.ui.history as history_module

    shown = []
    monkeypatch.setattr(history_module, "reveal", lambda path: shown.append(Path(path)))
    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 1))
    controller.refresh_queue()
    controller.bin_window.validate_selected()
    placed = controller.sb / "root" / NOEL / "06_Admin" / "2026-10-12_ACME_2026-042_Devis-impression.pdf"
    assert wait(qapp, placed.exists)
    history = controller.bin_window.history
    controller.bin_window.show_page("history")
    buttons = [b for b in history.findChildren(QPushButton) if b.text().startswith("Afficher") and b.isEnabled()]
    assert buttons
    for button in buttons:
        button.click()
    assert placed in shown  # le fichier rangé, sélectionné dans l'Explorateur

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    next(b for b in history.findChildren(QPushButton) if b.text() == "Annuler ce rangement").click()
    shown.clear()
    from tribin.ui.history import ExpandableRow

    def in_visible_row(button):  # les lignes d'avant l'annulation sont masquées en attendant leur destruction
        parent = button.parent()
        while parent is not None and not isinstance(parent, ExpandableRow):
            parent = parent.parent()
        return parent is not None and parent.isVisibleTo(history)

    for button in [b for b in history.findChildren(QPushButton)
                   if b.text().startswith("Afficher") and b.isEnabled() and in_visible_row(b)]:
        button.click()
    assert placed not in shown and any(p.name == "2026-10-12_ACME_2026-042_Devis-impression.pdf" or
                                       p.name == "scan0042.pdf" for p in shown)  # là où il est revenu


@pytest.mark.skipif(sys.platform != "win32", reason="menu du clic droit de l'Explorateur : Windows")
def test_context_menu_install_and_remove():
    import winreg

    from tribin.ui import system_integration as si

    key = r"Software\TriBinTests\shell\TriBin"  # clé de test : sans effet sur le vrai clic droit
    try:
        assert si.install_context_menu(key) == "clic droit › Trier avec TriBin"
        assert si.context_menu_installed(key)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            assert winreg.QueryValueEx(k, "")[0] == "Trier avec TriBin"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            command = winreg.QueryValueEx(k, "")[0]
        assert command.endswith('"%1"') and "tribin" in command.lower()
    finally:
        si.uninstall_context_menu(key)
        for leftover in (r"Software\TriBinTests\shell", r"Software\TriBinTests"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, leftover)
            except OSError:
                pass
    assert not si.context_menu_installed(key)


def test_hotkey_selection_parsing(tmp_path):
    from tribin.ui.hotkey import GROUP_SEPARATOR, explorer_selection, parse_selection

    out = "\n".join(["C:/a/un.pdf", "C:/a/deux.pdf", GROUP_SEPARATOR, ""])
    assert parse_selection(out) == [[Path("C:/a/un.pdf"), Path("C:/a/deux.pdf")]]
    assert len(parse_selection(f"x\n{GROUP_SEPARATOR}\ny\n{GROUP_SEPARATOR}\n")) == 2  # deux onglets
    assert explorer_selection(0) == ([], explorer_selection(0)[1]) and explorer_selection(0)[1]


@pytest.mark.skipif(sys.platform != "win32", reason="raccourci global : Windows")
def test_global_hotkey_registers_and_fires(qapp):
    import ctypes
    from ctypes import wintypes

    from tribin.ui.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, WM_HOTKEY, GlobalHotkey

    if qapp.platformName() != "windows":
        pytest.skip("affichage hors écran : pas de vraie fenêtre Windows pour RegisterHotKey")
    hotkey = GlobalHotkey()
    fired = []
    hotkey.triggered.connect(lambda: fired.append(True))
    try:
        assert hotkey.register(MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x7B)  # Ctrl+Alt+Maj+F12 : libre pour le test
        msg = wintypes.MSG(hwnd=int(hotkey.winId()), message=WM_HOTKEY, wParam=GlobalHotkey.HOTKEY_ID)
        assert hotkey.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))[0]
        assert fired == [True]
    finally:
        hotkey.unregister()
        hotkey.deleteLater()
    assert not hotkey.registered


def test_history_rows_expand_and_home_shows_stats(qapp, controller):
    from tribin.ui.history import ExpandableRow

    controller.drop_paths([controller.sb / "inbox" / "scan0042.pdf", controller.sb / "inbox" / "BC_4512.pdf"])
    assert wait(qapp, lambda: ready_items(controller, 2))
    controller.confirm_simulation = lambda report: True
    controller.refresh_queue()
    controller.bin_window.validate_all()
    assert wait(qapp, lambda: not controller.service.pending())
    win = controller.bin_window

    win.show_page("history")
    rows = [r for r in win.history.findChildren(ExpandableRow) if r.isVisibleTo(win.history)]
    assert len(rows) == 2 and not rows[0].details.isVisibleTo(rows[0])
    names = {r.name.toolTip() for r in rows}
    assert any("Devis-impression" in n for n in names), names  # le nom du fichier rangé, en tête de ligne
    rows[0].toggle()  # clic : détails dépliés (date, dossier, catégorie, confiance, décision)
    assert rows[0].details.isVisibleTo(rows[0])
    texts = [w.text() for w in rows[0].details.findChildren(QLabel)]
    assert {"Rangé le", "Dossier", "Catégorie", "Confiance de l'IA", "Décision"} <= set(texts)
    assert any("90 %" in t for t in texts)
    win.history.reload()  # l'état déplié est conservé
    qapp.processEvents()
    reopened = [r for r in win.history.findChildren(ExpandableRow) if r.isVisibleTo(win.history) and r.expanded]
    assert len(reopened) == 1

    win.show_page("home")
    home = win.home
    assert home.cards["filed"].target == 2 and home.cards["rate"].target == 100
    assert "Bonjour" in home.greeting.text() or "Bonsoir" in home.greeting.text()
    recent = [w for w in home.findChildren(QLabel) if "Devis-impression" in w.toolTip() and w.isVisibleTo(home)]
    assert recent  # parmi les 5 derniers rangements
