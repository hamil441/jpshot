"""The popup shown after a capture: English text, Japanese text (with dictionary hover) and audio."""
from __future__ import annotations

import html
import logging

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QKeySequence, QShortcut,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSlider, QTabWidget, QTextEdit,
                               QToolButton, QVBoxLayout, QWidget)

from . import japanese, translate
from .log import short
from .ocr import OcrResult, flatten
from .workers import run_async

log = logging.getLogger("jpshot.ui")

JP_FONTS = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic UI", "Meiryo", "Hiragino Sans",
            "Hiragino Kaku Gothic ProN", "MS Gothic", "IPAexGothic", "TakaoPGothic"]
MODES = [("original", "漢字  Original"), ("furigana", "Furigana"), ("hiragana", "ひらがな")]


def jp_font(size: int) -> QFont:
    f = QFont()
    f.setFamilies(JP_FONTS)
    f.setPointSize(size)
    return f


# ---------------------------------------------------------------------------
class JapaneseView(QTextEdit):
    """Read-only Japanese text. Hold Shift while hovering a word to look it up."""

    lookup_requested = Signal(object, QRect)  # Token, global rect of the word

    def __init__(self, font_size: int):
        super().__init__()
        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setFont(jp_font(font_size))
        self.viewport().setMouseTracking(True)
        self.spans: list[japanese.Span] = []
        self._hover: japanese.Span | None = None

    def set_content(self, text: str, spans: list[japanese.Span]):
        self.spans = spans
        self._hover = None
        self.setPlainText(text)
        self.setExtraSelections([])

    def clear_hover(self):
        self._hover = None
        self.setExtraSelections([])

    # Map a viewport point to the span under it (None if over blank space).
    def span_at(self, pos: QPoint) -> japanese.Span | None:
        doc_len = self.document().characterCount() - 1
        p = self.cursorForPosition(pos).position()
        for idx in (p - 1, p):
            if idx < 0 or idx >= doc_len:
                continue
            a = QTextCursor(self.document())
            a.setPosition(idx)
            b = QTextCursor(self.document())
            b.setPosition(idx + 1)
            ra, rb = self.cursorRect(a), self.cursorRect(b)
            right = rb.x() if rb.top() == ra.top() else ra.x() + ra.height()
            if ra.top() <= pos.y() <= ra.bottom() and min(ra.x(), right) <= pos.x() <= max(ra.x(), right):
                return japanese.span_at(self.spans, idx)
        return None

    def lookup_at(self, pos: QPoint):
        span = self.span_at(pos)
        if span is None or not span.token.lookupable or span is self._hover:
            return
        self._hover = span
        sel = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(232, 85, 109, 70))
        sel.format = fmt
        c = QTextCursor(self.document())
        c.setPosition(span.start)
        c.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = c
        self.setExtraSelections([sel])
        a = QTextCursor(self.document())
        a.setPosition(span.start)
        b = QTextCursor(self.document())
        b.setPosition(span.end)
        r = self.cursorRect(a).united(self.cursorRect(b))
        glob = QRect(self.viewport().mapToGlobal(r.topLeft()), r.size())
        log.debug("Hover %r (base %r, reading %r)", span.token.surface, span.token.base, span.token.reading)
        self.lookup_requested.emit(span.token, glob)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier and not (e.buttons() & Qt.MouseButton.LeftButton):
            self.lookup_at(e.position().toPoint())


# ---------------------------------------------------------------------------
class DictionaryPopup(QFrame):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("dictpopup")
        self.setStyleSheet("#dictpopup{background:palette(base);border:1px solid palette(mid);}")
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setFont(jp_font(11))
        self.label.setMaximumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(self.label)

    def _head(self, tok) -> str:
        h = f"<span style='font-size:20pt'><b>{html.escape(tok.surface)}</b></span>"
        if tok.reading and japanese.has_kanji(tok.surface):
            h += f"&nbsp;&nbsp;<span style='font-size:13pt;color:#e8556d'>{html.escape(tok.reading)}</span>"
        if tok.base and tok.base != tok.surface:
            h += f"<br><span style='color:gray'>dictionary form: {html.escape(tok.base)}</span>"
        return h

    def show_loading(self, tok, rect: QRect):
        self.label.setText(self._head(tok) + "<br><i style='color:gray'>Looking up…</i>")
        self._place(rect)

    def show_entries(self, tok, rect: QRect, entries, error: str):
        body = self._head(tok)
        if error:
            body += f"<p style='color:#c33'>Lookup failed: {html.escape(error)}</p>"
        elif not entries:
            body += "<p style='color:gray'>No dictionary entry found.</p>"
        for e in entries:
            body += (f"<p style='margin:8px 0 2px 0'><b>{html.escape(e.word)}</b>"
                     + (f" 【{html.escape(e.reading)}】" if e.reading and e.reading != e.word else "")
                     + "</p><ol style='margin:0'>")
            for s in e.senses:
                pos = f" <span style='color:gray;font-size:9pt'><i>{html.escape(', '.join(s.pos))}</i></span>" if s.pos else ""
                body += f"<li>{html.escape('; '.join(s.glosses))}{pos}</li>"
            body += "</ol>"
        self.label.setText(body)
        self._place(rect)

    def _place(self, rect: QRect):
        self.adjustSize()
        scr = (QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()).availableGeometry()
        x = min(max(rect.left(), scr.left()), scr.right() - self.width())
        y = rect.bottom() + 6
        if y + self.height() > scr.bottom():
            y = rect.top() - self.height() - 6
        self.move(x, max(y, scr.top()))
        self.show()
        self.raise_()


# ---------------------------------------------------------------------------
class ResultWindow(QWidget):
    def __init__(self, cfg, dictionary, speaker):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.cfg, self.dictionary, self.speaker = cfg, dictionary, speaker
        self.setWindowTitle("JPShot")
        self.resize(560, 420)

        self.source: OcrResult | None = None
        self.ja_text = ""
        self.ja_lines: list[list[japanese.Token]] = []
        self._req = 0
        self._lookup_req = 0
        self._lookup_ctx = None

        self.popup = DictionaryPopup()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_english(), "English")
        self.tabs.addTab(self._build_japanese(), "日本語  Japanese")
        self.tabs.currentChanged.connect(self._tab_changed)

        self.status = QLabel()
        self.status.setStyleSheet("color:gray")

        root = QVBoxLayout(self)
        root.addWidget(self.tabs, 1)
        root.addWidget(self._build_audio())
        root.addWidget(self.status)

        dictionary.finished.connect(self._lookup_done)
        speaker.state_changed.connect(self._speaker_state)
        QApplication.instance().installEventFilter(self)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence("["), self, lambda: self.speed.setValue(self.speed.value() - 10))
        QShortcut(QKeySequence("]"), self, lambda: self.speed.setValue(self.speed.value() + 10))
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.tabs.setCurrentIndex(1))

    # -- construction -----------------------------------------------------
    def _build_english(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.en_badge = QLabel()
        self.en_badge.setStyleSheet("color:gray")
        bar.addWidget(self.en_badge)
        bar.addStretch()
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: self._copy(self.en_text.toPlainText(), "English"))
        bar.addWidget(copy)
        lay.addLayout(bar)
        self.en_text = QPlainTextEdit()
        self.en_text.setReadOnly(True)
        f = self.en_text.font()
        f.setPointSize(13)
        self.en_text.setFont(f)
        lay.addWidget(self.en_text, 1)
        return w

    def _build_japanese(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for i, (key, label) in enumerate(MODES):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setChecked(key == self.cfg.japanese_mode)
            b.setToolTip(f"Show the Japanese as {label.split()[-1].lower()}  (Alt+{i + 1})")
            b.setShortcut(QKeySequence(f"Alt+{i + 1}"))
            self.mode_group.addButton(b, i)
            bar.addWidget(b)
        self.mode_group.idClicked.connect(self._mode_changed)
        bar.addStretch()
        self.ja_badge = QLabel()
        self.ja_badge.setStyleSheet("color:gray")
        bar.addWidget(self.ja_badge)
        copy = QPushButton("Copy")
        copy.setToolTip("Copy the Japanese text as currently shown")
        copy.clicked.connect(lambda: self._copy(self.ja_view.toPlainText(), "Japanese"))
        bar.addWidget(copy)
        lay.addLayout(bar)
        self.ja_view = JapaneseView(self.cfg.japanese_font_size)
        self.ja_view.lookup_requested.connect(self._lookup)
        lay.addWidget(self.ja_view, 1)
        hint = QLabel("Hold <b>Shift</b> and hover a word to look it up")
        hint.setStyleSheet("color:gray")
        lay.addWidget(hint)
        return w

    def _build_audio(self) -> QWidget:
        w = QFrame()
        w.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(w)
        self.play_btn = QPushButton("▶  Read in Japanese")
        self.play_btn.setMinimumWidth(170)
        self.play_btn.setToolTip("Play / stop  (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        lay.addWidget(self.play_btn)
        lay.addSpacing(10)
        lay.addWidget(QLabel("🐢"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(50, 200)          # percent
        self.speed.setSingleStep(5)
        self.speed.setPageStep(25)
        self.speed.setTickInterval(25)
        self.speed.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speed.setToolTip("Speech speed  ([ slower, ] faster)")
        self.speed.setValue(round(self.cfg.tts_speed * 100))
        lay.addWidget(self.speed, 1)
        lay.addWidget(QLabel("🐇"))
        self.speed_lbl = QLabel()
        self.speed_lbl.setMinimumWidth(48)
        lay.addWidget(self.speed_lbl)
        reset = QToolButton()
        reset.setText("1×")
        reset.setToolTip("Normal speed")
        reset.clicked.connect(lambda: self.speed.setValue(100))
        lay.addWidget(reset)
        self._speed_timer = QTimer(self, singleShot=True, interval=450)
        self._speed_timer.timeout.connect(self._apply_speed)
        self.speed.valueChanged.connect(self._speed_changed)
        self._speed_changed(self.speed.value(), restart=False)
        return w

    # -- showing a new capture -------------------------------------------
    def show_result(self, res: OcrResult, anchor: QRect):
        self._req += 1
        req = self._req
        self.source = res
        self.speaker.stop()
        self.popup.hide()
        log.info("Showing result window (%s source)", res.language)

        if res.language == "ja":
            self._set_japanese(res.text)
            self.ja_badge.setText("from screenshot")
            self.en_badge.setText("translated")
            self.en_text.setPlainText("Translating…")
            src, dst, text = "ja", "en", flatten(res.text, "ja")
        else:
            self.en_text.setPlainText(res.text)
            self.en_badge.setText("from screenshot")
            self.ja_badge.setText("translated")
            self._set_japanese("")
            self.ja_view.setPlainText("翻訳中… (translating)")
            src, dst, text = "en", "ja", flatten(res.text, "en")
        self.status.setText(f"OCR confidence {res.confidence:.0f}%")

        run_async(translate.translate, text, src, dst, self.cfg.translator,
                  on_done=lambda out: self._translated(req, src, out),
                  on_error=lambda msg: self._translate_failed(req, msg))

        self.tabs.setCurrentIndex(self.cfg.last_tab if self.cfg.last_tab in (0, 1) else 1)
        self._place_near(anchor)
        self.show()
        self.raise_()
        self.activateWindow()

    def _translated(self, req, src, out: str):
        if req != self._req:
            log.debug("Discarding stale translation")
            return
        if src == "ja":
            self.en_text.setPlainText(out)
        else:
            self._set_japanese(out)
        self.status.setText(self.status.text() + "  ·  translated")

    def _translate_failed(self, req, msg):
        if req != self._req:
            return
        log.error("Translation failed: %s", msg)
        target = self.en_text if self.source and self.source.language == "ja" else None
        if target:
            target.setPlainText(f"(Translation failed: {msg})")
        else:
            self.ja_view.setPlainText(f"(Translation failed: {msg})")
        self.status.setText("Translation failed — see terminal for details")

    def _set_japanese(self, text: str):
        self.ja_text = text
        try:
            self.ja_lines = japanese.tokenize(text) if text else []
        except Exception:
            log.exception("Japanese tokenizer failed; hover lookup and readings disabled")
            self.ja_lines = [[japanese.Token(line, "", line, "", "", False)] for line in text.split("\n")]
        self._render_japanese()
        self.play_btn.setEnabled(bool(text.strip()))

    def _render_japanese(self):
        text, spans = japanese.render(self.ja_lines, self.cfg.japanese_mode)
        self.ja_view.set_content(text, spans)

    def _place_near(self, anchor: QRect):
        scr = (QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()).availableGeometry()
        x = anchor.right() + 16
        if x + self.width() > scr.right():
            x = anchor.left() - self.width() - 16
        if x < scr.left():
            x = scr.right() - self.width() - 16
        y = min(max(anchor.top(), scr.top() + 10), scr.bottom() - self.height() - 40)
        self.move(x, y)

    # -- Japanese view ----------------------------------------------------
    def _mode_changed(self, idx: int):
        self.cfg.japanese_mode = MODES[idx][0]
        self.cfg.save()
        log.debug("Japanese display mode -> %s", self.cfg.japanese_mode)
        self.popup.hide()
        self._render_japanese()

    def _lookup(self, tok, rect: QRect):
        self._lookup_req += 1
        self._lookup_ctx = (self._lookup_req, tok, rect)
        self.popup.show_loading(tok, rect)
        self.dictionary.lookup(self._lookup_req, tok.candidates())

    def _lookup_done(self, req_id, query, entries, error):
        if not self._lookup_ctx or req_id != self._lookup_ctx[0]:
            return
        _, tok, rect = self._lookup_ctx
        if self.isVisible():
            self.popup.show_entries(tok, rect, entries, error)

    # -- audio ------------------------------------------------------------
    def _speed_value(self) -> float:
        return round(self.speed.value() / 5) * 5 / 100

    def _speed_changed(self, _v, restart=True):
        self.speed_lbl.setText(f"{self._speed_value():.2f}×")
        if restart:
            self._speed_timer.start()

    def _apply_speed(self):
        self.cfg.tts_speed = self._speed_value()
        self.cfg.save()
        log.info("Speech speed -> %.2f×", self.cfg.tts_speed)
        self.speaker.change_speed(self.cfg.tts_speed)

    def toggle_play(self):
        if self.speaker.busy():
            self.speaker.stop()
            return
        text = flatten(self.ja_text, "ja")
        if not text:
            return
        log.info("Read aloud at %.2f×: %s", self._speed_value(), short(text))
        self.speaker.play(text, self._speed_value())

    def _speaker_state(self, state: str):
        if state == "loading":
            self.play_btn.setText("…  Generating")
        elif state == "playing":
            self.play_btn.setText("■  Stop")
        else:
            self.play_btn.setText("▶  Read in Japanese")
            if state.startswith("error:"):
                self.status.setText(f"Audio error: {state[6:]}")

    # -- misc -------------------------------------------------------------
    def _copy(self, text: str, what: str):
        QGuiApplication.clipboard().setText(text)
        self.status.setText(f"Copied {what} text to clipboard")
        log.debug("Copied %s: %s", what, short(text))

    def _tab_changed(self, idx):
        self.popup.hide()
        self.cfg.last_tab = idx
        self.cfg.save()

    def _escape(self):
        if self.popup.isVisible():
            self.popup.hide()
            self.ja_view.clear_hover()
        else:
            self.hide()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Shift and not ev.isAutoRepeat() \
                and self.isVisible() and self.tabs.currentIndex() == 1:
            pos = self.ja_view.viewport().mapFromGlobal(QCursor.pos())
            if self.ja_view.viewport().rect().contains(pos):
                self.ja_view.clear_hover()
                self.ja_view.lookup_at(pos)
        elif t == QEvent.Type.MouseButtonPress and self.popup.isVisible() and obj is self.ja_view.viewport():
            self.popup.hide()
            self.ja_view.clear_hover()
        return False

    def hideEvent(self, e):
        self.popup.hide()
        self.ja_view.clear_hover()
        self.speaker.stop()
        super().hideEvent(e)
