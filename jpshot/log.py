"""Terminal logging. INFO by default, DEBUG with --debug (or JPSHOT_DEBUG=1)."""
from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager

log = logging.getLogger("jpshot")


class _Fmt(logging.Formatter):
    COLORS = {"DEBUG": "\033[90m", "INFO": "\033[36m", "WARNING": "\033[33m",
              "ERROR": "\033[31m", "CRITICAL": "\033[41m"}

    def __init__(self, color: bool):
        super().__init__("%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%H:%M:%S")
        self.color = color

    def format(self, record):
        s = super().format(record)
        if self.color:
            s = f"{self.COLORS.get(record.levelname, '')}{s}\033[0m"
        return s


def setup(debug: bool = False) -> None:
    debug = debug or os.environ.get("JPSHOT_DEBUG") == "1"
    handler = logging.StreamHandler(sys.stderr)
    color = sys.stderr.isatty() and (os.name != "nt" or "WT_SESSION" in os.environ)
    handler.setFormatter(_Fmt(color))
    root = logging.getLogger("jpshot")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False

    # Route Qt's own warnings into the same log.
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        qtlog = logging.getLogger("jpshot.qt")
        levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
                  QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
                  QtMsgType.QtFatalMsg: logging.CRITICAL}
        qInstallMessageHandler(lambda t, _ctx, msg: qtlog.log(levels.get(t, logging.INFO), msg))
    except Exception:  # noqa: BLE001
        pass

    # Uncaught exceptions (including ones raised inside Qt slots) go to the log too.
    def _hook(exc_type, exc, tb):
        logging.getLogger("jpshot").critical("Uncaught exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = _hook


@contextmanager
def timed(logger: logging.Logger, what: str):
    t = time.perf_counter()
    try:
        yield
    finally:
        logger.debug("%s took %.0f ms", what, (time.perf_counter() - t) * 1000)


def short(text: str, n: int = 80) -> str:
    text = text.replace("\n", " ⏎ ")
    return text if len(text) <= n else text[: n - 1] + "…"
