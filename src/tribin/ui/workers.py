"""Tâches en arrière-plan (QThreadPool) : l'interface ne gèle jamais."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Exécute `fn` dans un fil d'arrière-plan ; émet finished(résultat) ou failed(message)."""

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # message lisible pour l'utilisateur, détail dans tribin.log
            log.error("background task failed: %s\n%s", exc, traceback.format_exc())
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


def run_task(fn: Callable, *args, on_done: Callable | None = None, on_error: Callable | None = None, **kwargs) -> Task:
    task = Task(fn, *args, **kwargs)
    if on_done:
        task.signals.finished.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task
