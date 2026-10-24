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
from tribin.service.bin import BinError, BinService, Validation
from tribin.ui.icons import bin_icon
from tribin.ui.workers import run_task

log = logging.getLogger(__name__)

MAX_WRITE_RETRIES = 5
RETRY_MS = 5000


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
        self.tray = Tray(self)
        self._tasks: set = set()
        self._history = None
        if show_ui:
            self.tray.show()
            screen = app.primaryScreen().availableGeometry()
            self.drop_widget.move(screen.right() - 140, screen.bottom() - 180)
            self.drop_widget.show()

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
        items = self.service.pending()
        self.bin_window.refresh(items)
        self.tray.set_count(len(items))
        self.drop_widget.set_count(len(items))

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
                    self.error(f"« {path.name} » est encore en cours d'écriture : réessaie plus tard.")
                return
            self.refresh_queue()
            self._analyze(result.file_id)

        self._run(stage, on_done=done)

    def _analyze(self, file_id: str) -> None:
        self._run(self.service.analyze, file_id, on_done=lambda _: self.refresh_queue())

    def validate(self, validations: list[Validation], force_simulation: bool = False) -> None:
        def prepared(p) -> None:
            if not p.report.ok:
                QMessageBox.warning(self.bin_window, "Simulation : problème détecté",
                                    "Rien n'a été déplacé.\n\n" + "\n".join(p.report.lines()))
                return
            if p.needs_confirmation or force_simulation:
                box = QMessageBox(QMessageBox.Icon.Question, "Simulation", f"{len(p.validations)} fichier(s) à ranger. "
                                  "Voici ce qui va être fait (rien n'a encore été touché) :",
                                  QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self.bin_window)
                box.setDetailedText("\n".join(p.report.lines()))
                box.setInformativeText("\n".join(p.report.lines()[:12]))
                if box.exec() != QMessageBox.StandardButton.Ok:
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

        self._run(self.service.prepare, validations, on_done=prepared)

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
        self.refresh_queue()
        self.bin_window.show()
        self.bin_window.raise_()
        self.bin_window.activateWindow()

    def show_history(self) -> None:
        from tribin.ui.history import HistoryWindow

        self._history = HistoryWindow(self)
        self._history.show()

    def show_settings(self) -> None:
        from tribin.ui.settings import SettingsDialog

        if SettingsDialog(self).exec():
            self.refresh_queue()

    def set_drop_widget_visible(self, visible: bool) -> None:
        self.drop_widget.setVisible(visible)

    def start(self, initial_paths: list[Path]) -> None:
        """Après l'onboarding : reprend les analyses interrompues puis traite les fichiers reçus au lancement."""
        self.refresh_queue()
        self._run(self.service.check_implicit_corrections)
        for item in self.service.recover():
            self._analyze(item.file_id)
        if initial_paths:
            self.drop_paths(initial_paths)
            self.show_bin()

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
    paths = [Path(a) for a in argv[1:] if not a.startswith("-") and Path(a).exists()]
    setup_logging()
    app = TriBinApplication(argv)
    app.setApplicationName("TriBin")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(bin_icon())
    install_french_translations(app)
    if _send_to_running_instance(paths):
        return 0  # une instance tourne déjà : elle s'occupe des fichiers
    controller = AppController(app)
    app.controller = controller
    server = _listen(controller)  # noqa: F841 — doit rester en vie
    if not controller.service.config.onboarding_done:
        from tribin.ui.onboarding import OnboardingWizard

        if not OnboardingWizard(controller).exec():
            return 0
    try:
        controller.service.convention()
    except BinError as exc:
        QMessageBox.warning(None, "TriBin", f"{exc}\nOuvre les réglages pour corriger.")
    controller.start(paths + app.pending_opens)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
