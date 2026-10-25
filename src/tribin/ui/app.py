"""Application de bureau TriBin : point d'entrée, instance unique, ouverture de fichiers (Dock, raccourci, Envoyer vers)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from tribin.config import get_settings, setup_logging
from tribin.fs.filters import is_being_written
from tribin.llm import make_provider
from tribin.llm.base import LLMError
from tribin.service.bin import AUTO_MIN_CONFIDENCE, READY_MIN_CONFIDENCE, AutoReport, BinError, BinService, Validation
from tribin.ui.icons import app_icon
from tribin.ui.theme import apply_theme
from tribin.ui.workers import run_task

log = logging.getLogger(__name__)

MAX_WRITE_RETRIES = 5
RETRY_MS = 5000
NOTICE_MS = 1500  # regroupe les notifications des analyses qui se terminent presque en même temps


def server_name() -> str:
    return f"TriBin-{get_settings().user}"


class TriBinApplication(QApplication):
    """Reçoit aussi les fichiers déposés sur l'icône du Dock (macOS, QFileOpenEvent)."""

    def __init__(self, argv: list[str]):
        super().__init__(argv)
        self.pending_opens: list[Path] = []
        self.controller: AppController | None = None

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = Path(event.file()) if isinstance(event, QFileOpenEvent) else None
            if path is None:
                return super().event(event)
            if self.controller:
                self.controller.drop_paths([path])
            else:
                self.pending_opens.append(path)
            return True
        return super().event(event)


class AppController:
    def __init__(self, app: TriBinApplication, service: BinService | None = None, show_ui: bool = True):
        from tribin.ui.bin_window import BinWindow
        from tribin.ui.drop_widget import DropWidget
        from tribin.ui.tray import Tray

        self.app = app
        self.service = service or BinService(get_settings())
        self.bin_window = BinWindow(self)
        self.drop_widget = DropWidget()
        self.drop_widget.files_dropped.connect(self.drop_paths)
        self.drop_widget.clicked.connect(self.show_bin)
        self.drop_widget.auto_clicked.connect(self.auto_file_ready)
        self.tray = Tray(self)
        self._tasks: set = set()
        self.show_ui = show_ui
        self.hotkey = None  # raccourci clavier global, créé au démarrage (jamais pendant les tests)
        self._notice = {"done": 0, "review": []}  # rangés automatiquement / laissés pour avis, à annoncer
        self._notice_timer = QTimer()
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(NOTICE_MS)
        self._notice_timer.timeout.connect(self._flush_notice)
        self.confirm_simulation = self._show_simulation  # remplaçable dans les tests
        if show_ui:
            self.tray.show()
            screen = app.primaryScreen().availableGeometry()
            self.drop_widget.move(screen.right() - 260, screen.bottom() - 220)
            self.drop_widget.show()
            self.drop_widget.keep_on_screen()

    # --- utilitaires --------------------------------------------------------------------------

    def _run(self, fn, *args, on_done=None, on_error=None):
        task = run_task(fn, *args, on_done=on_done, on_error=on_error or self.error)
        self._tasks.add(task)
        task.signals.finished.connect(lambda *_: self._tasks.discard(task))
        task.signals.failed.connect(lambda *_: self._tasks.discard(task))
        return task

    def error(self, message: str) -> None:
        self.tray.showMessage("TriBin", message)
        if self.bin_window.isVisible():
            self.bin_window.statusBar().showMessage(message, 10000)
        log.info("user-facing error: %s", message)

    def llm_or_none(self):
        try:
            return make_provider(self.service.ai_settings(), self.service.config.model or None)
        except LLMError:
            return None

    # --- file d'attente -----------------------------------------------------------------------

    def refresh_queue(self) -> None:
        from tribin.ui.queue_panel import group_of

        items = self.service.pending()
        self.bin_window.refresh(items, self.service.set_aside_items())
        self.tray.set_count(len(items))
        groups = [group_of(i) for i in items]
        self.drop_widget.set_state(total=len(items), analyzing=groups.count("wait"), ready=groups.count("ready"),
                                   check=groups.count("check"))

    def drop_paths(self, paths: list[Path]) -> None:
        for path in paths:
            self._drop_one(Path(path), 0)

    def _drop_one(self, path: Path, attempt: int) -> None:
        def stage() -> object:
            if path.is_file() and is_being_written(path):
                return "busy"
            return self.service.drop(path)

        def done(result) -> None:
            if result == "busy":
                if attempt < MAX_WRITE_RETRIES:
                    QTimer.singleShot(RETRY_MS, lambda: self._drop_one(path, attempt + 1))
                else:
                    self.error(f"« {path.name} » est encore en cours d'écriture : réessayez plus tard.")
                return
            self.refresh_queue()
            self._analyze(result.file_id)

        self._run(stage, on_done=done)

    def _analyze(self, file_id: str) -> None:
        def analyzed(_) -> None:
            self.refresh_queue()
            if self.service.config.auto_file:
                threshold = self.service.config.auto_min_confidence or AUTO_MIN_CONFIDENCE
                self._run(self.service.auto_file, [file_id], threshold, on_done=self._auto_done)

        self._run(self.service.analyze, file_id, on_done=analyzed)

    # --- rangement automatique ------------------------------------------------------------------

    def auto_file_ready(self) -> None:
        """Bouton du widget : range tous les fichiers « prêts », sans ouvrir la fenêtre."""
        self._run(self.service.auto_file, None, READY_MIN_CONFIDENCE, on_done=self._auto_done)

    def _auto_done(self, report: AutoReport) -> None:
        self.refresh_queue()
        self._notice["done"] += len(report.done)
        self._notice["review"] += [item.name for item, _ in report.left]
        if report.done or report.left:
            self._notice_timer.start()

    def _flush_notice(self) -> None:
        done, review = self._notice["done"], self._notice["review"]
        self._notice = {"done": 0, "review": []}
        lines = []
        if done:
            lines.append(f"{done} fichier{'s' if done > 1 else ''} rangé{'s' if done > 1 else ''} automatiquement "
                         "(annulable depuis l'Historique).")
        if review:
            names = f"« {review[0]} »" if len(review) == 1 else f"{len(review)} fichiers"
            lines.append(f"{names} demande{'nt' if len(review) > 1 else ''} votre avis : cliquez pour ouvrir TriBin.")
        if lines:
            self.tray.showMessage("TriBin", "\n".join(lines))

    def validate(self, validations: list[Validation], force_simulation: bool = False) -> None:
        def prepared(p) -> None:
            if not p.report.ok or p.needs_confirmation or force_simulation:
                # Lot, création de dossier ou problème : la simulation DOIT être montrée (section 3.1).
                if not self.confirm_simulation(p.report) or not p.report.ok:
                    return
            self._run(self.service.commit, p, on_done=committed)

        def committed(result) -> None:
            self.refresh_queue()
            failed = result.failed
            if failed:
                self.error("\n".join(f"{op.source.name if op.source else op.destination.name} : {op.error}"
                                     for op in failed))
            else:
                self.bin_window.statusBar().showMessage(
                    f"{len([o for o in result.done if o.action == 'move'])} fichier(s) rangé(s) — annulable depuis l'Historique.", 8000)

        self._run(self.service.prepare, validations, on_done=prepared, on_error=self._validation_failed)

    def _validation_failed(self, message: str) -> None:
        """Rangement refusé : message bien visible (et pas seulement dans la barre d'état)."""
        self.error(message)
        if self.bin_window.isVisible():
            QMessageBox.warning(self.bin_window, "Rangement impossible", message)

    def return_to_origin(self, file_id: str) -> None:
        def done(message: str) -> None:
            self.refresh_queue()
            self.bin_window.statusBar().showMessage(message, 8000)

        self._run(self.service.return_to_origin, file_id, on_done=done)

    def remap(self) -> None:
        def work() -> str:
            from tribin.engine.context import ensure_profiles
            from tribin.mapping.profiles import describe_profiles, save_profiles

            convention = self.service.convention()
            llm = self.llm_or_none()
            total = 0
            for root in self.service.config.root_paths():
                profiles = ensure_profiles(self.service.db, root, convention)
                if llm:
                    describe_profiles(profiles, llm)
                    save_profiles(self.service.db, root, profiles)
                total += len(profiles)
            self.service.update_config(self.service.config)  # recharge les contextes
            return f"Cartographie à jour : {total} dossiers."

        self._run(work, on_done=lambda msg: self.tray.showMessage("TriBin", msg))

    # --- fenêtres -----------------------------------------------------------------------------

    def show_bin(self) -> None:
        """Ouvre la fenêtre : sur « À ranger » s'il y a des fichiers en attente, sinon là où elle était."""
        self.refresh_queue()
        if self.service.pending():
            self.bin_window.show_page("bin")
        self.bin_window.show()
        self.bin_window.raise_()
        self.bin_window.activateWindow()

    def _show_simulation(self, report) -> bool:
        from tribin.ui.simulation_dialog import SimulationDialog

        return SimulationDialog(report, self.bin_window).exec() == SimulationDialog.DialogCode.Accepted

    def show_history(self) -> None:
        self.show_bin()
        self.bin_window.show_page("history")

    def show_settings(self) -> None:
        from tribin.ui.settings import SettingsDialog

        dialog = SettingsDialog(self)
        if dialog.exec():
            if getattr(dialog, "naming_changed", False):
                self.service.rebuild_pending_names()  # noms proposés des fichiers en attente, selon le nouveau nommage
            self.apply_hotkey()
            self.retry_without_ai()
            self.refresh_queue()

    def refresh_all(self) -> None:
        """« Actualiser » (bouton, F5) : relit clé et réglages, relance les analyses restées sans IA,
        met à jour la liste et l'Historique."""
        self.service.reload()
        retried = self.service.retry_without_ai()
        for file_id in retried:
            self._analyze(file_id)
        self.refresh_queue()
        if self.bin_window.pages.currentWidget() is self.bin_window.history:
            self.bin_window.history.reload()
        self.bin_window.statusBar().showMessage(
            f"Actualisé : {len(retried)} fichier{'s' if len(retried) > 1 else ''} relancé{'s' if len(retried) > 1 else ''}"
            " en analyse." if retried else "Actualisé.", 5000)

    def reanalyze(self, file_id: str) -> None:
        """« Réanalyser » : nouvelle proposition de l'IA pour ce fichier."""
        self.service.reload()
        self.service.reanalyze(file_id)
        self.refresh_queue()
        self._analyze(file_id)

    def set_aside(self, file_id: str) -> None:
        """« Mettre de côté » : hors de la liste « À ranger », sans rien déplacer."""
        self.service.set_aside(file_id)
        self.refresh_queue()
        self.bin_window.statusBar().showMessage("Fichier mis de côté : retrouvez-le dans l'onglet « Mis de côté ».", 6000)

    def resume(self, file_id: str) -> None:
        """« Remettre à ranger »."""
        if self.service.resume(file_id) == "analyzing":
            self._analyze(file_id)
        self.refresh_queue()

    def retry_without_ai(self) -> None:
        """Nouvelle clé ou nouveau fournisseur : relance l'analyse des fichiers « à traiter à la main »."""
        for file_id in self.service.retry_without_ai():
            self._analyze(file_id)

    def show_account(self) -> None:
        from tribin.ui.account import AccountDialog

        if AccountDialog(self).exec():
            self.bin_window.update_account()
            self.bin_window.home.reload()

    def set_drop_widget_visible(self, visible: bool) -> None:
        self.drop_widget.setVisible(visible)

    def requeue_returned(self) -> None:
        """Rangements annulés : les fichiers revenus dans le dossier tampon repassent « à ranger »."""
        for file_id in self.service.requeue_returned():
            self._analyze(file_id)

    def start(self, initial_paths: list[Path]) -> None:
        """Après l'onboarding : reprend les analyses interrompues puis traite les fichiers reçus au lancement."""
        self.requeue_returned()  # y compris ceux annulés avant que TriBin ne sache les remettre dans la liste
        self.refresh_queue()
        self._run(self.service.check_implicit_corrections)
        self.service.retry_without_ai()  # analyses restées sans IA (clé ou module absent la dernière fois)
        for item in self.service.recover():
            self._analyze(item.file_id)
        if initial_paths:
            self.drop_paths(initial_paths)
            self.show_bin()
        self.apply_hotkey()

    # --- raccourci clavier global ---------------------------------------------------------------

    def apply_hotkey(self) -> None:
        """Active ou coupe Ctrl + Alt + T selon les réglages (Windows, application visible seulement)."""
        if not self.show_ui or sys.platform != "win32":
            return
        from tribin.ui.hotkey import GlobalHotkey

        if self.hotkey is None:
            self.hotkey = GlobalHotkey()
            self.hotkey.triggered.connect(self._hotkey_pressed)
        if self.service.config.hotkey:
            self.hotkey.register()
        else:
            self.hotkey.unregister()

    def _hotkey_pressed(self) -> None:
        from tribin.ui.hotkey import explorer_selection, foreground_window

        hwnd = foreground_window()  # tout de suite : la fenêtre au premier plan au moment de l'appui

        def done(result) -> None:
            paths, message = result
            if paths:
                self.drop_paths(paths)
                n = len(paths)
                self.tray.showMessage("TriBin", f"{n} fichier{'s' if n > 1 else ''} envoyé{'s' if n > 1 else ''} "
                                                "à TriBin.")
            else:
                self.tray.showMessage("TriBin", message)

        self._run(explorer_selection, hwnd, on_done=done)

    def quit(self) -> None:
        self.app.quit()


def _send_to_running_instance(paths: list[Path]) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(500):
        return False
    socket.write((json.dumps([str(p) for p in paths]) + "\n").encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def _listen(controller: AppController) -> QLocalServer:
    server = QLocalServer()
    QLocalServer.removeServer(server_name())  # nettoie un éventuel serveur orphelin (plantage précédent)
    server.listen(server_name())

    def on_connection() -> None:
        sock = server.nextPendingConnection()

        def read() -> None:
            data = bytes(sock.readAll()).decode("utf-8", errors="replace")
            for line in data.splitlines():
                try:
                    paths = [Path(p) for p in json.loads(line)]
                except json.JSONDecodeError:
                    continue
                if paths:
                    controller.drop_paths(paths)
                controller.show_bin()

        sock.readyRead.connect(read)

    server.newConnection.connect(on_connection)
    return server


def install_french_translations(app: QApplication) -> None:
    """Boutons standard de Qt (Oui, Non, Annuler…) en français, si les traductions sont disponibles."""
    translator = QTranslator(app)
    if translator.load(QLocale(QLocale.Language.French), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        app._fr_translator = translator  # garder une référence


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--diagnostic" in argv:  # rapport d'installation (fournisseurs d'IA, trousseau), sans interface
        from tribin.diagnostic import write_report

        write_report(get_settings().data_dir)
        return 0
    paths = [Path(a) for a in argv[1:] if not a.startswith("-") and Path(a).exists()]
    setup_logging()
    app = TriBinApplication(argv)
    app.setApplicationName("TriBin")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    apply_theme(app)
    install_french_translations(app)
    if _send_to_running_instance(paths):
        return 0  # une instance tourne déjà : elle s'occupe des fichiers
    controller = AppController(app)
    app.controller = controller
    server = _listen(controller)  # noqa: F841 — doit rester en vie
    if not controller.service.config.onboarding_done or "--onboarding" in argv:  # --onboarding : le revoir
        from tribin.ui.onboarding import OnboardingWizard

        if not OnboardingWizard(controller).exec():
            return 0
    try:
        controller.service.convention()
    except BinError as exc:
        QMessageBox.warning(None, "TriBin", f"{exc}\nOuvrez les réglages pour corriger.")
    controller.start(paths + app.pending_opens)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
