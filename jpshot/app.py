"""Tray app: global hotkey -> capture -> OCR -> result window. Single instance via a local socket."""
from __future__ import annotations

import getpass
import logging
import os
import sys

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import japanese, ocr, theme
from .capture import CaptureSession, pixmap_to_pil
from .dictionary import Dictionary
from .tts import Speaker
from .settings import SettingsDialog
from .ui_result import ResultWindow
from .workers import run_async

log = logging.getLogger("jpshot.app")
SERVER_NAME = f"jpshot-{getpass.getuser()}"


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#e8556d"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    f = QFont()
    f.setFamilies(["Noto Sans CJK JP", "Yu Gothic UI", "Hiragino Sans", "Meiryo"])
    f.setPixelSize(40)
    f.setBold(True)
    p.setFont(f)
    p.setPen(Qt.GlobalColor.white)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "訳")
    p.end()
    return QIcon(pm)


def send_to_running(command: str) -> bool:
    """Return True if another instance is running and received the command."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(command.encode())
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    log.info("Sent %r to the running JPShot instance", command)
    return True


class JPShotApp(QObject):
    capture_requested = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.session: CaptureSession | None = None
        self.had_result = False
        self.busy = False

        ocr.configure(cfg.tesseract_cmd)
        self.dictionary = Dictionary(cfg.dictionary)
        self._apply_story_settings()
        self.speaker = Speaker(cfg)
        from . import lookupkey
        lookupkey.set_key(cfg.lookup_key)
        self.result = ResultWindow(cfg, self.dictionary, self.speaker)
        self.result.settings_requested.connect(self.open_settings)
        self.result.theme_toggled.connect(self.toggle_theme)
        self.result.mine_requested.connect(self.open_mine)
        self.mine_dialog = None
        self._capture_callback = None
        self.settings_dialog: SettingsDialog | None = None
        self.hotkey_listener = None

        self.capture_requested.connect(self.start_capture, Qt.ConnectionType.QueuedConnection)
        self._setup_server()
        self._setup_tray()
        self._setup_hotkey()
        QTimer.singleShot(0, self._warm_up)

    # -- setup ------------------------------------------------------------
    def _warm_up(self):
        try:
            japanese.get_tagger()
        except Exception:
            log.exception("Could not load the Japanese tokenizer (pip install fugashi unidic-lite)")

    def _setup_server(self):
        QLocalServer.removeServer(SERVER_NAME)
        self.server = QLocalServer(self)
        if not self.server.listen(SERVER_NAME):
            log.warning("Could not open control socket: %s", self.server.errorString())
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        sock = self.server.nextPendingConnection()

        def read():
            cmd = bytes(sock.readAll()).decode(errors="ignore").strip()
            log.info("Received command %r", cmd)
            if cmd == "capture":
                self.capture_requested.emit()
            elif cmd == "show" and self.had_result:
                self.result.show()
                self.result.raise_()
            elif cmd == "settings":
                self.open_settings()
            elif cmd == "quit":
                QApplication.quit()
        sock.readyRead.connect(read)

    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("No system tray available; use the hotkey or `python -m jpshot capture`")
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        hk = self.cfg.hotkey or "no hotkey"
        self.tray.setToolTip(f"JPShot — {hk}")
        menu = QMenu()
        a = QAction(f"Capture  ({hk})", menu)
        a.triggered.connect(self.capture_requested.emit)
        menu.addAction(a)
        a = QAction("Show last result", menu)
        a.triggered.connect(lambda: self.had_result and (self.result.show(), self.result.raise_()))
        menu.addAction(a)
        a = QAction("Settings…", menu)
        a.triggered.connect(self.open_settings)
        menu.addAction(a)
        menu.addSeparator()
        a = QAction("Quit", menu)
        a.triggered.connect(QApplication.quit)
        menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and self.capture_requested.emit())
        self.tray.show()
        self._menu = menu

    def _setup_hotkey(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        if not self.cfg.hotkey:
            log.info("Global hotkey disabled in config")
            return
        if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            log.warning("Wayland session: global hotkeys from apps usually don't work. Bind "
                        "`python -m jpshot capture` to a key in your desktop's keyboard settings.")
        try:
            from pynput import keyboard

            def fire():
                log.debug("Hotkey %s pressed", self.cfg.hotkey)
                self.capture_requested.emit()  # thread-safe: queued to the UI thread

            self.hotkey_listener = keyboard.GlobalHotKeys({self.cfg.hotkey: fire})
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
            log.info("Global hotkey registered: %s", self.cfg.hotkey)
            self._active_hotkey = self.cfg.hotkey
        except Exception as e:  # noqa: BLE001
            log.error("Could not register global hotkey %r: %s. Use the tray icon or bind "
                      "`python -m jpshot capture` to a key in your OS settings.", self.cfg.hotkey, e)

    # -- settings / theme ---------------------------------------------------
    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self.cfg)
            self.settings_dialog.applied.connect(self.apply_settings)
        else:
            self.settings_dialog.sync_sections()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def apply_settings(self):
        old_hotkey = getattr(self, "_active_hotkey", None)
        theme.apply(self.cfg.theme)
        ocr.configure(self.cfg.tesseract_cmd)
        self.dictionary.set_backend(self.cfg.dictionary)
        self._apply_story_settings()
        self.result.apply_settings()
        if self.cfg.hotkey != old_hotkey:
            self._setup_hotkey()

    def _apply_story_settings(self):
        k = self.dictionary.kanji
        k.provider = self.cfg.story_provider
        k.api_key = self.cfg.anthropic_api_key.strip()
        k.story_model = self.cfg.story_model.strip() or "claude-haiku-5-5"
        k.ollama_url = self.cfg.ollama_url.strip().rstrip("/") or "http://127.0.0.1:11434"
        k.ollama_model = self.cfg.ollama_model.strip() or "qwen2.5:7b"
        k._ollama_ok = None

    def toggle_theme(self):
        self.cfg.theme = "light" if theme.is_dark(self.cfg.theme) else "dark"
        self.cfg.save()
        theme.apply(self.cfg.theme)
        self.result.apply_settings()

    # -- Anki mining --------------------------------------------------------
    def open_mine(self):
        from .mine import MineDialog

        if self.mine_dialog is not None:
            self.mine_dialog.close()
            self.mine_dialog.deleteLater()
        self.mine_dialog = MineDialog(self.cfg, self.result.mining_data(), self.capture_image, self.result)
        self.mine_dialog.added.connect(lambda nid: self.result.status.setText(f"Anki card added (note {nid})"))
        self.mine_dialog.show()
        self.mine_dialog.raise_()

    def capture_image(self, callback):
        """Capture a region and hand back the image only (no OCR) — used while mining."""
        if self.session is not None or self.busy:
            return
        self.result._hide_popup()
        self._capture_callback = callback
        QTimer.singleShot(60, self._grab)

    # -- capture flow -----------------------------------------------------
    def start_capture(self):
        if self.session is not None or self.busy:
            log.debug("Capture already in progress; ignoring")
            return
        log.info("Starting capture")
        # The result window stays open; only the dictionary popup is hidden.
        self.result._hide_popup()
        QTimer.singleShot(60, self._grab)

    def _grab(self):
        self.session = CaptureSession()
        self.session.selected.connect(self._on_selected)
        self.session.cancelled.connect(self._on_cancelled)

    def _on_cancelled(self):
        self.session = None
        self._capture_callback = None

    def _on_selected(self, pixmap, rect: QRect):
        self.session = None
        if self._capture_callback is not None:
            cb, self._capture_callback = self._capture_callback, None
            cb(pixmap)
            return
        self.process_image(pixmap_to_pil(pixmap), rect, pixmap)

    def process_image(self, img, anchor: QRect, pixmap=None):
        self.busy = True
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        run_async(ocr.recognize, img, self.cfg.ocr_languages, self.cfg.ocr_min_confidence,
                  self.cfg.ocr_min_chars,
                  on_done=lambda res: self._on_ocr(res, anchor, pixmap),
                  on_error=self._on_ocr_error)

    def _on_ocr(self, res, anchor, pixmap=None):
        self.busy = False
        QApplication.restoreOverrideCursor()
        if res is None:
            return  # nothing detected -> nothing happens
        self.had_result = True
        self.result.show_result(res, anchor, pixmap)

    def _on_ocr_error(self, msg):
        self.busy = False
        QApplication.restoreOverrideCursor()
        log.error("OCR failed: %s", msg)
        if self.tray:
            self.tray.showMessage("JPShot", f"OCR failed: {msg}", QSystemTrayIcon.MessageIcon.Warning, 4000)

    def shutdown(self):
        log.info("Shutting down")
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        self.speaker.stop()
