"""Japanese text-to-speech with adjustable speed (edge-tts neural voices, gTTS fallback)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .workers import run_async

log = logging.getLogger("jpshot.tts")

CACHE_DIR = Path(tempfile.gettempdir()) / "jpshot-tts"


def _edge(text: str, voice: str, speed: float, path: Path) -> None:
    import edge_tts

    rate = f"{round((speed - 1) * 100):+d}%"

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))

    asyncio.run(go())


def synthesize(text: str, speed: float, engine: str, voice: str) -> tuple[Path, float]:
    """Return (mp3 path, playback rate to apply)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if engine == "edge":
        key = hashlib.sha1(f"edge|{voice}|{speed:.2f}|{text}".encode()).hexdigest()
        path = CACHE_DIR / f"{key}.mp3"
        if path.exists() and path.stat().st_size:
            log.debug("TTS cache hit %s", path.name)
            return path, 1.0
        log.debug("edge-tts voice=%s speed=%.2f text=%r", voice, speed, text)
        tmp = path.with_suffix(".part")
        try:
            _edge(text, voice, speed, tmp)
            tmp.replace(path)
            return path, 1.0
        except Exception as e:  # noqa: BLE001
            log.warning("edge-tts failed (%s); falling back to gTTS", e)

    from gtts import gTTS

    key = hashlib.sha1(f"gtts|{text}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.mp3"
    if not (path.exists() and path.stat().st_size):
        tmp = path.with_suffix(".part")
        log.debug("gTTS text=%r", text)
        gTTS(text=text, lang="ja").save(str(tmp))
        tmp.replace(path)
    return path, speed  # gTTS has no rate control, so speed up/slow down playback instead


class Speaker(QObject):
    state_changed = Signal(str)  # "idle" | "loading" | "playing" | "error:<msg>"

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.player.playbackStateChanged.connect(self._on_playback)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)
        self._req = 0
        self._loading = False
        self._seek: float | None = None
        self._text = ""

    # -- public -----------------------------------------------------------
    def busy(self) -> bool:
        return self._loading or self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def play(self, text: str, speed: float, fraction: float = 0.0) -> None:
        if not text.strip():
            return
        self._req += 1
        req = self._req
        self._text = text
        self.player.stop()
        self._loading = True
        self.state_changed.emit("loading")
        run_async(synthesize, text, speed, self.cfg.tts_engine, self.cfg.tts_voice,
                  on_done=lambda res: self._ready(req, res, fraction),
                  on_error=lambda msg: self._failed(req, msg))

    def stop(self) -> None:
        self._req += 1
        self._loading = False
        self.player.stop()
        self.state_changed.emit("idle")

    def change_speed(self, speed: float) -> None:
        """Restart at the new speed from roughly the same spot, if currently playing."""
        if not self.busy() or not self._text:
            return
        dur = self.player.duration()
        frac = self.player.position() / dur if dur > 0 and not self._loading else 0.0
        self.play(self._text, speed, frac)

    # -- internals --------------------------------------------------------
    def _ready(self, req, res, fraction):
        if req != self._req:
            return
        self._loading = False
        path, rate = res
        log.info("Playing audio %s (playback rate %.2f%s)", path.name, rate,
                 f", resume at {fraction:.0%}" if fraction > 0.02 else "")
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.setPlaybackRate(rate)
        self._seek = fraction if fraction > 0.02 else None
        self.player.play()
        self._apply_seek()

    def _failed(self, req, msg):
        if req != self._req:
            return
        self._loading = False
        log.error("Speech synthesis failed: %s", msg)
        self.state_changed.emit(f"error:{msg}")

    def _apply_seek(self):
        st = self.player.mediaStatus()
        if self._seek is not None and self.player.duration() > 0 and st in (
            QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
        ):
            self.player.setPosition(int(self.player.duration() * self._seek))
            self._seek = None

    def _on_error(self, err, msg):
        log.error("Audio player error %s: %s", err, msg)
        self.state_changed.emit(f"error:{msg}")

    def _on_status(self, st):
        log.debug("media status: %s", st)
        self._apply_seek()

    def _on_playback(self, st):
        if st == QMediaPlayer.PlaybackState.PlayingState:
            self.state_changed.emit("playing")
        elif not self._loading:
            self.state_changed.emit("idle")
