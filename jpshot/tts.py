"""Japanese text-to-speech with adjustable speed and a library of voices.

Voice ids are "<engine>:<name>":
  edge:ja-JP-NanamiNeural   Microsoft neural voices via edge-tts (online)
  gtts:ja                   Google Translate's voice (online)
  voicevox:<style id>       VOICEVOX — dozens of free Japanese character voices; detected
                            automatically while the VOICEVOX app/engine runs (port 50021)
  aivis:<style id>          AivisSpeech — same API, port 10101
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .workers import run_async

log = logging.getLogger("jpshot.tts")

CACHE_DIR = Path(tempfile.gettempdir()) / "jpshot-tts"
LOCAL_ENGINES = {
    "voicevox": ("VOICEVOX", os.environ.get("JPSHOT_VOICEVOX_URL", "http://127.0.0.1:50021")),
    "aivis": ("AivisSpeech", os.environ.get("JPSHOT_AIVIS_URL", "http://127.0.0.1:10101")),
}
BUILTIN_VOICES = [
    ("edge:ja-JP-NanamiNeural", "Nanami (Microsoft, female)"),
    ("edge:ja-JP-KeitaNeural", "Keita (Microsoft, male)"),
    ("gtts:ja", "Google Translate voice"),
]
DEFAULT_VOICE = "edge:ja-JP-NanamiNeural"


@dataclass
class Voice:
    id: str
    name: str
    engine: str


_voices_cache: tuple[float, list[Voice]] | None = None
_voices_lock = threading.Lock()


def available_voices(refresh: bool = False) -> list[Voice]:
    """Built-in voices plus every voice of any local VOICEVOX/AivisSpeech engine that's running."""
    global _voices_cache
    with _voices_lock:
        if _voices_cache and not refresh and time.time() - _voices_cache[0] < 60:
            return _voices_cache[1]
        import requests

        voices = [Voice(i, n, i.split(":")[0]) for i, n in BUILTIN_VOICES]
        for engine, (label, url) in LOCAL_ENGINES.items():
            try:
                r = requests.get(f"{url}/speakers", timeout=0.8)
                r.raise_for_status()
                n = 0
                for sp in r.json():
                    for st in sp.get("styles", []):
                        if st.get("type", "talk") != "talk":
                            continue
                        voices.append(Voice(f"{engine}:{st['id']}", f"{label}: {sp['name']}（{st['name']}）", engine))
                        n += 1
                log.info("%s detected at %s: %d voices", label, url, n)
            except Exception as e:  # noqa: BLE001
                log.debug("%s not running at %s (%s)", label, url, type(e).__name__)
        _voices_cache = (time.time(), voices)
        return voices


def voice_name(voice_id: str) -> str:
    for v in available_voices():
        if v.id == voice_id:
            return v.name
    return voice_id


def normalize_voice(voice_id: str) -> str:
    if not voice_id:
        return DEFAULT_VOICE
    if ":" not in voice_id:            # old config: a bare edge voice name
        return f"edge:{voice_id}"
    return voice_id


def _edge(text: str, voice: str, speed: float, path: Path) -> None:
    import edge_tts

    rate = f"{round((speed - 1) * 100):+d}%"

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))

    asyncio.run(go())


def _local_engine(engine: str, style: str, text: str, speed: float, path: Path) -> None:
    import requests

    url = LOCAL_ENGINES[engine][1]
    q = requests.post(f"{url}/audio_query", params={"text": text, "speaker": style}, timeout=30)
    q.raise_for_status()
    query = q.json()
    query["speedScale"] = speed
    r = requests.post(f"{url}/synthesis", params={"speaker": style}, json=query, timeout=60)
    r.raise_for_status()
    path.write_bytes(r.content)


def _cached(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def synthesize(text: str, speed: float, voice_id: str) -> tuple[Path, float]:
    """Return (audio file, playback rate to apply). Falls back to another voice on failure."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    voice_id = normalize_voice(voice_id)
    engine, _, name = voice_id.partition(":")
    key = hashlib.sha1(f"{voice_id}|{speed:.2f}|{text}".encode()).hexdigest()

    if engine == "edge":
        path = CACHE_DIR / f"{key}.mp3"
        if _cached(path):
            return path, 1.0
        log.debug("edge-tts voice=%s speed=%.2f text=%r", name, speed, text)
        tmp = path.with_suffix(".part")
        try:
            _edge(text, name, speed, tmp)
            tmp.replace(path)
            return path, 1.0
        except Exception as e:  # noqa: BLE001
            log.warning("edge-tts failed (%s); falling back to Google voice", e)
            return synthesize(text, speed, "gtts:ja")

    if engine in LOCAL_ENGINES:
        path = CACHE_DIR / f"{key}.wav"
        if _cached(path):
            return path, 1.0
        log.debug("%s style=%s speed=%.2f text=%r", engine, name, speed, text)
        tmp = path.with_suffix(".part")
        try:
            _local_engine(engine, name, text, speed, tmp)
            tmp.replace(path)
            return path, 1.0
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed (%s) — is it running? Falling back to %s",
                        LOCAL_ENGINES[engine][0], e, DEFAULT_VOICE)
            return synthesize(text, speed, DEFAULT_VOICE)

    from gtts import gTTS

    key = hashlib.sha1(f"gtts|{text}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.mp3"
    if not _cached(path):
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
        run_async(synthesize, text, speed, self.cfg.voice,
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
