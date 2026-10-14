"""Shadowing practice: hear the sentence, record yourself, compare — including a pitch-contour graph."""
from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

log = logging.getLogger("jpshot.shadow")
SR = 16000


# --- audio analysis (no Qt) ---------------------------------------------------------
def load_mono(path: str | Path):
    """Decode any audio file to mono float32 at 16 kHz (ffmpeg if available, else WAV only)."""
    import numpy as np

    path = str(path)
    if shutil.which("ffmpeg"):
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                             capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            return np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        log.warning("ffmpeg could not decode %s: %s", path, out.stderr[:200])
    with wave.open(path, "rb") as w:
        n, ch, rate, width = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(n)
    if width != 2:
        raise RuntimeError("only 16-bit WAV can be read without ffmpeg (install ffmpeg)")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != SR:   # simple resample
        idx = np.linspace(0, len(x) - 1, int(len(x) * SR / rate))
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    return x


def pitch_track(x, hop: int = 160, win: int = 640, fmin: float = 70, fmax: float = 450):
    """Fundamental frequency (Hz, NaN where unvoiced) every 10 ms, by autocorrelation."""
    import numpy as np

    if len(x) < win:
        return np.array([])
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    rms = np.sqrt((frames ** 2).mean(axis=1))
    gate = max(0.01, 0.12 * np.percentile(rms, 95))
    lo, hi = int(SR / fmax), int(SR / fmin)
    f0 = np.full(len(frames), np.nan, dtype=np.float32)
    window = np.hanning(win).astype(np.float32)
    for i, fr in enumerate(frames):
        if rms[i] < gate:
            continue
        y = (fr - fr.mean()) * window
        spec = np.fft.rfft(y, 2 * win)
        ac = np.fft.irfft(spec * np.conj(spec))[:win]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.35:
            f0[i] = SR / k
    # median-smooth voiced runs
    out = f0.copy()
    for i in range(len(f0)):
        w = f0[max(0, i - 2):i + 3]
        w = w[~np.isnan(w)]
        if not np.isnan(f0[i]) and len(w):
            out[i] = np.median(w)
    return out


def contour(path: str | Path):
    """Pitch in semitones relative to the speaker's median, plus duration in seconds."""
    import numpy as np

    x = load_mono(path)
    f0 = pitch_track(x)
    voiced = f0[~np.isnan(f0)]
    if not len(voiced):
        return [], len(x) / SR
    ref = float(np.median(voiced))
    semis = [12 * math.log2(v / ref) if not math.isnan(v) else math.nan for v in f0]
    # trim leading/trailing silence so both contours line up
    first = next((i for i, v in enumerate(semis) if not math.isnan(v)), 0)
    last = len(semis) - next((i for i, v in enumerate(reversed(semis)) if not math.isnan(v)), 0)
    return semis[first:last], len(x) / SR


# --- Qt dialog ---------------------------------------------------------------------
def _dialog_class():
    from PySide6.QtCore import QPointF, Qt, QUrl
    from PySide6.QtGui import QColor, QPainter, QPalette, QPen
    from PySide6.QtMultimedia import (QAudioInput, QAudioOutput, QMediaCaptureSession, QMediaFormat,
                                      QMediaPlayer, QMediaRecorder)
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

    from .workers import run_async

    REF_COLOR, YOU_COLOR = QColor("#5aa9ff"), QColor("#ff8a3d")

    class PitchPlot(QWidget):
        def __init__(self):
            super().__init__()
            self.ref: list[float] = []
            self.you: list[float] = []
            self.setMinimumHeight(150)

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pal = self.palette()
            p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base))
            w, h = self.width(), self.height()
            p.setPen(QPen(pal.color(QPalette.ColorRole.Mid), 1, Qt.PenStyle.DashLine))
            p.drawLine(0, h // 2, w, h // 2)
            if not self.ref and not self.you:
                p.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                           "Record yourself to compare your pitch with the reference")
                return
            for series, col in ((self.ref, REF_COLOR), (self.you, YOU_COLOR)):
                if not series:
                    continue
                p.setPen(QPen(col, 2.2))
                n = len(series)
                prev = None
                for i, v in enumerate(series):
                    if math.isnan(v):
                        prev = None
                        continue
                    pt = QPointF(8 + (w - 16) * i / max(1, n - 1), h / 2 - max(-9, min(9, v)) * (h / 2 - 8) / 9)
                    if prev is not None:
                        p.drawLine(prev, pt)
                    prev = pt
            p.setPen(REF_COLOR)
            p.drawText(8, 16, "reference")
            p.setPen(YOU_COLOR)
            p.drawText(90, 16, "you")

    class ShadowDialog(QDialog):
        def __init__(self, sentence: str, voice: str, speed: float, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Shadowing practice")
            self.sentence, self.voice, self.speed = sentence, voice, speed
            self.ref_path: str | None = None
            self.rec_path = Path(tempfile.gettempdir()) / "jpshot-tts" / f"shadow-{int(time.time())}.wav"
            self.rec_path.parent.mkdir(parents=True, exist_ok=True)

            self.player = QMediaPlayer(self)
            self.out = QAudioOutput(self)
            self.player.setAudioOutput(self.out)
            self.player.mediaStatusChanged.connect(self._media_status)
            self._queue: list[str] = []

            self.session = QMediaCaptureSession(self)
            self.mic = QAudioInput(self)
            self.session.setAudioInput(self.mic)
            self.recorder = QMediaRecorder(self)
            self.session.setRecorder(self.recorder)
            fmt = QMediaFormat(QMediaFormat.FileFormat.Wave)
            self.recorder.setMediaFormat(fmt)
            self.recorder.setQuality(QMediaRecorder.Quality.HighQuality)
            self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self.rec_path)))
            self.recorder.recorderStateChanged.connect(self._rec_state)
            self.recorder.errorOccurred.connect(lambda _e, msg: self.status.setText(f"Recording error: {msg}"))

            text = QLabel(f"<span style='font-size:16pt'>{sentence}</span>")
            text.setWordWrap(True)
            how = QLabel("Listen, then record yourself saying it right after (or along with) the voice. "
                         "Compare by ear and on the pitch graph — try to match the rises and drops.")
            how.setWordWrap(True)
            how.setStyleSheet("color:gray")
            self.ref_btn = QPushButton("▶ Reference")
            self.ref_btn.clicked.connect(lambda: self._play([self.ref_path]))
            self.rec_btn = QPushButton("● Record")
            self.rec_btn.clicked.connect(self._toggle_record)
            self.you_btn = QPushButton("▶ You")
            self.you_btn.clicked.connect(lambda: self._play([str(self.rec_path)]))
            self.both_btn = QPushButton("▶ Both")
            self.both_btn.clicked.connect(lambda: self._play([self.ref_path, str(self.rec_path)]))
            for b in (self.ref_btn, self.you_btn, self.both_btn):
                b.setEnabled(False)
            row = QHBoxLayout()
            for b in (self.ref_btn, self.rec_btn, self.you_btn, self.both_btn):
                row.addWidget(b)
            self.plot = PitchPlot()
            self.status = QLabel("Preparing the reference audio…")
            self.status.setStyleSheet("color:gray")
            lay = QVBoxLayout(self)
            lay.addWidget(text)
            lay.addWidget(how)
            lay.addLayout(row)
            lay.addWidget(self.plot, 1)
            lay.addWidget(self.status)
            self.resize(560, 380)

            from .tts import synthesize
            run_async(synthesize, sentence, speed, voice, on_done=self._ref_ready,
                      on_error=lambda m: self.status.setText(f"Couldn't make the reference audio: {m}"))

        # reference
        def _ref_ready(self, res):
            self.ref_path = str(res[0])
            self.ref_btn.setEnabled(True)
            self.status.setText("Ready. Press ▶ Reference, then ● Record.")
            run_async(contour, self.ref_path, on_done=self._ref_contour,
                      on_error=lambda m: log.warning("Reference pitch failed: %s", m))
            self._play([self.ref_path])

        def _ref_contour(self, res):
            self.plot.ref = res[0]
            self.plot.update()

        # playback (a small queue so ▶ Both plays one after the other)
        def _play(self, paths):
            self._queue = [p for p in paths if p]
            self._next()

        def _next(self):
            if not self._queue:
                return
            self.player.setSource(QUrl.fromLocalFile(self._queue.pop(0)))
            self.player.play()

        def _media_status(self, st):
            if st == QMediaPlayer.MediaStatus.EndOfMedia:
                self._next()

        # recording
        def _toggle_record(self):
            if self.recorder.recorderState() == QMediaRecorder.RecorderState.RecordingState:
                self.recorder.stop()
            else:
                self.player.stop()
                self.recorder.record()

        def _rec_state(self, state):
            if state == QMediaRecorder.RecorderState.RecordingState:
                self.rec_btn.setText("■ Stop")
                self.status.setText("Recording… speak now")
            else:
                self.rec_btn.setText("● Record")
                path = self.recorder.actualLocation().toLocalFile() or str(self.rec_path)
                self.rec_path = Path(path)
                if self.rec_path.exists():
                    self.you_btn.setEnabled(True)
                    self.both_btn.setEnabled(bool(self.ref_path))
                    self.status.setText("Analysing your pitch…")
                    run_async(contour, str(self.rec_path), on_done=self._you_contour,
                              on_error=lambda m: self.status.setText(f"Couldn't analyse the recording: {m}"))

        def _you_contour(self, res):
            self.plot.you = res[0]
            self.plot.update()
            self.status.setText(f"Your take: {res[1]:.1f}s. ▶ Both plays the reference then you.")

    return ShadowDialog


def open_dialog(sentence: str, voice: str, speed: float, parent=None):
    dlg = _dialog_class()(sentence, voice, speed, parent)
    dlg.show()
    return dlg
