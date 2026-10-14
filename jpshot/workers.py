"""Run blocking work (OCR, network, TTS) off the UI thread and get results back on it."""
from __future__ import annotations

import logging
import time

log = logging.getLogger("jpshot.worker")

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()  # created on the UI thread => slots run on the UI thread

    def run(self):
        name = getattr(self.fn, "__qualname__", repr(self.fn))
        t = time.perf_counter()
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:  # noqa: BLE001
            log.exception("%s failed after %.0f ms", name, (time.perf_counter() - t) * 1000)
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        else:
            log.debug("%s finished in %.0f ms", name, (time.perf_counter() - t) * 1000)
            self.signals.done.emit(result)


_alive: set[_Task] = set()


def run_async(fn, *args, on_done=None, on_error=None, **kwargs) -> None:
    task = _Task(fn, args, kwargs)
    task.setAutoDelete(False)
    _alive.add(task)

    def _cleanup(*_):
        _alive.discard(task)

    q = Qt.ConnectionType.QueuedConnection
    if on_done:
        task.signals.done.connect(on_done, q)
    if on_error:
        task.signals.failed.connect(on_error, q)
    task.signals.done.connect(_cleanup, q)
    task.signals.failed.connect(_cleanup, q)
    QThreadPool.globalInstance().start(task)
