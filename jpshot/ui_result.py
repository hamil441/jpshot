"""The window shown after a capture.

A row of toggles at the top (English · 日本語 · Furigana · ひらがな · Rōmaji) picks which rows are
shown; every shown row is visible at once, selectable and copyable. Selecting part of any row
translates just that part. Hold Shift over a Japanese word for a popup with its dictionary entry,
grammar role and kanji breakdown; in Grammar mode words are color-coded by part of speech and a
plain hover is enough. Audio bar with a speed slider at the bottom.
"""
from __future__ import annotations

import html
import logging

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QClipboard, QColor, QCursor, QFont, QGuiApplication, QKeySequence,
                           QPixmap, QShortcut, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from . import grammar, japanese, kanji, theme, translate
from .furigana_view import FuriganaView
from .config import ALL_SECTIONS
from .log import short
from .ocr import OcrResult, flatten
from .workers import run_async

log = logging.getLogger("jpshot.ui")

JP_FONTS = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic UI", "Meiryo", "Hiragino Sans",
            "Hiragino Kaku Gothic ProN", "MS Gothic", "IPAexGothic", "TakaoPGothic"]
SECTION_TITLES = {"english": "English", "japanese": "日本語", "furigana": "Furigana",
                  "hiragana": "ひらがな", "romaji": "Rōmaji"}
RENDER_MODE = {"japanese": "original", "furigana": "furigana", "hiragana": "hiragana", "romaji": "romaji"}

CSS = f"""
QToolButton#chip {{ padding: 3px 11px; border: 1px solid palette(mid); border-radius: 11px; }}
QToolButton#chip:checked {{ background: {theme.ACCENT}; color: white; border-color: {theme.ACCENT}; }}
QLabel#sectionTitle {{ font-weight: 600; }}
QLabel#muted {{ color: palette(placeholder-text); }}
"""


def jp_font(size: int) -> QFont:
    f = QFont()
    f.setFamilies(JP_FONTS)
    f.setPointSize(size)
    return f


def copy_text(text: str) -> None:
    """Copy to the clipboard (and the X11 primary selection, for middle-click paste)."""
    cb = QGuiApplication.clipboard()
    cb.setText(text, QClipboard.Mode.Clipboard)
    if cb.supportsSelection():
        cb.setText(text, QClipboard.Mode.Selection)
    log.info("Copied text to clipboard (%d chars): %s", len(text), short(text))


def copy_image(pm: QPixmap) -> None:
    QGuiApplication.clipboard().setPixmap(pm, QClipboard.Mode.Clipboard)
    log.info("Copied image to clipboard (%dx%d)", pm.width(), pm.height())


# ---------------------------------------------------------------------------
class WordView(QTextEdit):
    """Read-only text. If it has word spans, holding Shift while hovering looks words up."""

    lookup_requested = Signal(object, QRect)  # Token, global rect of the word

    def __init__(self, font: QFont):
        super().__init__()
        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setFont(font)
        self.setMinimumHeight(44)
        self.viewport().setMouseTracking(True)
        self.spans: list[japanese.Span] = []
        self._hover: japanese.Span | None = None
        self.hover_lookup = False   # grammar mode: look up on plain hover
        self._colored = False

    def set_content(self, text: str, spans: list[japanese.Span] | None = None):
        self.spans = spans or []
        self._hover = None
        self._colored = False
        self.setPlainText(text)
        self.setExtraSelections([])
        if self.hover_lookup:
            self.set_colors(True)

    def set_colors(self, on: bool):
        """Color each word by its part of speech (grammar mode)."""
        if on == self._colored or (on and not self.spans):
            return
        cur = QTextCursor(self.document())
        cur.beginEditBlock()
        if not on:
            cur.select(QTextCursor.SelectionType.Document)
            cur.setCharFormat(QTextCharFormat())
        else:
            for span in self.spans:
                col = grammar.color_for(span.token)
                if not col:
                    continue
                cur.setPosition(span.start)
                cur.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(col))
                cur.mergeCharFormat(fmt)
        cur.endEditBlock()
        self._colored = on

    def original_of_selection(self) -> str:
        """Selected text; in a Japanese row, mapped back to the original words."""
        c = self.textCursor()
        a, b = c.selectionStart(), c.selectionEnd()
        if a == b:
            return ""
        if not self.spans:
            return c.selectedText().replace("\u2029", "\n")
        out = []
        for sp in self.spans:
            if sp.end > a and sp.start < b:
                if out and sp.token.space_before:
                    out.append(sp.token.space_before)
                out.append(sp.token.surface)
        return "".join(out)

    def clear_hover(self):
        self._hover = None
        self.setExtraSelections([])

    def span_at(self, pos: QPoint) -> japanese.Span | None:
        if not self.spans:
            return None
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
        fmt.setBackground(QColor(232, 85, 109, 80))
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
        if (self.hover_lookup or e.modifiers() & Qt.KeyboardModifier.ShiftModifier) \
                and not (e.buttons() & Qt.MouseButton.LeftButton):
            self.lookup_at(e.position().toPoint())


class Section(QWidget):
    def __init__(self, key: str, font: QFont):
        super().__init__()
        self.key = key
        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        title = QLabel(SECTION_TITLES[key])
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        self.badge = QLabel()
        self.badge.setObjectName("muted")
        head.addWidget(self.badge)
        head.addStretch()
        self.copy_btn = QToolButton()
        self.copy_btn.setText("Copy")
        self.copy_btn.setToolTip(f"Copy the {SECTION_TITLES[key]} text")
        self.copy_btn.setAutoRaise(True)
        self.copy_btn.clicked.connect(lambda: copy_text(self.view.toPlainText()))
        head.addWidget(self.copy_btn)
        self.view = FuriganaView(font) if key == "furigana" else WordView(font)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(head)
        lay.addWidget(self.view, 1)


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
        self.label.setMaximumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(self.label)

    def _head(self, tok) -> str:
        h = f"<span style='font-size:20pt'><b>{html.escape(tok.surface)}</b></span>"
        if tok.reading and tok.reading != tok.surface:
            h += f"&nbsp;&nbsp;<span style='font-size:13pt;color:{theme.ACCENT}'>{html.escape(tok.reading)}</span>"
        h += f"&nbsp;&nbsp;<span style='color:gray'>{html.escape(japanese.romaji_of(tok))}</span>"
        if tok.base and tok.base != tok.surface:
            h += f"<br><span style='color:gray'>dictionary form: {html.escape(tok.base)}</span>"
        return h

    def show_info(self, tok, rect: QRect, gram_html: str, entries, error: str, kanji_html: str,
                  loading: bool):
        body = self._head(tok) + gram_html
        if loading:
            body += "<br><i style='color:gray'>Looking up…</i>"
        elif error:
            body += f"<p style='color:#d44'>Lookup failed: {html.escape(error)}</p>"
        elif not entries:
            body += "<p style='color:gray'>No dictionary entry found.</p>"
        for e in (entries or [])[:3]:
            body += (f"<p style='margin:8px 0 2px 0'><b>{html.escape(e.word)}</b>"
                     + (f" 【{html.escape(e.reading)}】" if e.reading and e.reading != e.word else "")
                     + "</p><ol style='margin:0'>")
            for s in e.senses[:4]:
                pos = (f" <span style='color:gray;font-size:9pt'><i>{html.escape(', '.join(s.pos))}</i></span>"
                       if s.pos else "")
                body += f"<li>{html.escape('; '.join(s.glosses))}{pos}</li>"
            body += "</ol>"
        body += kanji_html
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
    settings_requested = Signal()
    theme_toggled = Signal()

    def __init__(self, cfg, dictionary, speaker):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.cfg, self.dictionary, self.speaker = cfg, dictionary, speaker
        self.setWindowTitle("JPShot")
        self.setStyleSheet(CSS)
        self.resize(600, 640)

        self.source: OcrResult | None = None
        self.pixmap: QPixmap | None = None
        self.ja_text = ""
        self.ja_lines: list[list[japanese.Token]] = []
        self._req = 0
        self._lookup_req = 0
        self._lookup_ctx = None
        self._placed = False
        self._sel_req = 0
        self._sel_view: WordView | None = None
        self._sel_timer = QTimer(self, singleShot=True, interval=450)
        self._sel_timer.timeout.connect(self._translate_selection)

        self.popup = DictionaryPopup()

        # sections, stacked in a splitter so rows can be resized
        self.sections: dict[str, Section] = {}
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        for key in ALL_SECTIONS:
            sec = Section(key, self._font_for(key))
            sec.view.lookup_requested.connect(self._lookup)
            sec.view.viewport().installEventFilter(self)
            sec.view.selectionChanged.connect(lambda v=sec.view: self._selection_changed(v))
            self.sections[key] = sec
            self.splitter.addWidget(sec)

        self.status = QLabel()
        self.status.setObjectName("muted")
        hint = QLabel("Hold <b>Shift</b> over a Japanese word to look it up")
        hint.setObjectName("muted")
        foot = QHBoxLayout()
        foot.addWidget(self.status, 1)
        foot.addWidget(hint)

        self.legend = QLabel(grammar.legend_html())
        self.legend.setObjectName("muted")
        self.legend.setWordWrap(True)

        root = QVBoxLayout(self)
        root.addLayout(self._build_toolbar())
        root.addWidget(self.legend)
        root.addWidget(self._build_selection_bar())
        root.addWidget(self.splitter, 1)
        root.addWidget(self._build_audio())
        root.addLayout(foot)

        self._apply_section_visibility()
        self._apply_grammar_mode()
        dictionary.finished.connect(self._lookup_done)
        dictionary.kanji_finished.connect(self._kanji_done)
        speaker.state_changed.connect(self._speaker_state)
        QApplication.instance().installEventFilter(self)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence("["), self, lambda: self.speed.setValue(self.speed.value() - 10))
        QShortcut(QKeySequence("]"), self, lambda: self.speed.setValue(self.speed.value() + 10))
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._copy_image)
        QShortcut(QKeySequence("Ctrl+,"), self, self.settings_requested.emit)

    # -- construction -----------------------------------------------------
    def _font_for(self, key: str) -> QFont:
        if key == "english":
            f = QFont()
            f.setPointSize(int(self.cfg.english_font_size))
            return f
        if key == "romaji":
            f = QFont()
            f.setPointSize(max(9, int(self.cfg.japanese_font_size) - 5))
            return f
        return jp_font(int(self.cfg.japanese_font_size))

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.chips: dict[str, QToolButton] = {}
        for i, key in enumerate(ALL_SECTIONS):
            b = QToolButton()
            b.setObjectName("chip")
            b.setText(SECTION_TITLES[key])
            b.setCheckable(True)
            b.setToolTip(f"Show/hide {SECTION_TITLES[key]}  (Alt+{i + 1})")
            b.setShortcut(QKeySequence(f"Alt+{i + 1}"))
            b.toggled.connect(lambda on, k=key: self._section_toggled(k, on))
            self.chips[key] = b
            bar.addWidget(b)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        bar.addWidget(sep)
        self.grammar_btn = QToolButton()
        self.grammar_btn.setObjectName("chip")
        self.grammar_btn.setText("Grammar")
        self.grammar_btn.setCheckable(True)
        self.grammar_btn.setToolTip("Color words by part of speech; hover a word to see its role, "
                                    "tense and form  (Alt+G)")
        self.grammar_btn.setShortcut(QKeySequence("Alt+G"))
        self.grammar_btn.setChecked(bool(self.cfg.grammar_mode))
        self.grammar_btn.toggled.connect(self._grammar_toggled)
        bar.addWidget(self.grammar_btn)
        bar.addStretch()
        self.copy_img_btn = QToolButton()
        self.copy_img_btn.setText("Copy image")
        self.copy_img_btn.setToolTip("Copy the screenshot to the clipboard  (Ctrl+Shift+C)")
        self.copy_img_btn.setEnabled(False)
        self.copy_img_btn.clicked.connect(self._copy_image)
        bar.addWidget(self.copy_img_btn)
        self.theme_btn = QToolButton()
        self.theme_btn.setToolTip("Switch light / dark")
        self.theme_btn.clicked.connect(self.theme_toggled.emit)
        bar.addWidget(self.theme_btn)
        gear = QToolButton()
        gear.setText("⚙")
        gear.setToolTip("Settings  (Ctrl+,)")
        gear.clicked.connect(self.settings_requested.emit)
        bar.addWidget(gear)
        self.update_theme_button()
        return bar

    def _build_selection_bar(self) -> QWidget:
        self.selbar = QFrame()
        self.selbar.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(self.selbar)
        lay.setContentsMargins(8, 4, 4, 4)
        self.sel_label = QLabel()
        self.sel_label.setWordWrap(True)
        self.sel_label.setTextFormat(Qt.TextFormat.RichText)
        self.sel_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sel_label.setFont(jp_font(12))
        lay.addWidget(self.sel_label, 1)
        self._sel_result = ""
        copy = QToolButton()
        copy.setText("Copy")
        copy.setAutoRaise(True)
        copy.setToolTip("Copy this translation")
        copy.clicked.connect(lambda: self._sel_result and copy_text(self._sel_result))
        lay.addWidget(copy)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.clicked.connect(self.selbar.hide)
        lay.addWidget(close)
        self.selbar.hide()
        return self.selbar

    def _build_audio(self) -> QWidget:
        w = QFrame()
        w.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(w)
        self.play_btn = QPushButton("▶  Read in Japanese")
        self.play_btn.setMinimumWidth(170)
        self.play_btn.setToolTip("Play / stop  (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.setEnabled(False)
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
        self.speed.setValue(round(float(self.cfg.tts_speed) * 100))
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

    # -- settings / theme -------------------------------------------------
    def update_theme_button(self):
        dark = theme.is_dark(self.cfg.theme)
        self.theme_btn.setText("☀" if dark else "☾")

    def apply_settings(self):
        """Re-read fonts, sections and theme from the config (after the settings dialog)."""
        for key, sec in self.sections.items():
            sec.view.setFont(self._font_for(key))
        self._apply_section_visibility()
        self.grammar_btn.setChecked(bool(self.cfg.grammar_mode))
        self.update_theme_button()
        self.setStyleSheet("")
        self.setStyleSheet(CSS)

    def _grammar_toggled(self, on: bool):
        self.cfg.grammar_mode = on
        self.cfg.save()
        self._hide_popup()
        self._apply_grammar_mode()
        log.info("Grammar mode %s", "on" if on else "off")

    def _apply_grammar_mode(self):
        on = bool(self.cfg.grammar_mode)
        self.legend.setVisible(on)
        for key, sec in self.sections.items():
            if key in RENDER_MODE:
                sec.view.hover_lookup = on
                sec.view.set_colors(on)

    def _apply_section_visibility(self):
        shown = set(self.cfg.sections)
        for key, chip in self.chips.items():
            chip.blockSignals(True)
            chip.setChecked(key in shown)
            chip.blockSignals(False)
            self.sections[key].setVisible(key in shown)

    def _section_toggled(self, key: str, on: bool):
        self.sections[key].setVisible(on)
        self.cfg.sections = [k for k in ALL_SECTIONS if self.chips[k].isChecked()]
        self.cfg.save()
        self._hide_popup()
        log.debug("Sections shown: %s", self.cfg.sections)

    # -- showing a new capture -------------------------------------------
    def show_result(self, res: OcrResult, anchor: QRect, pixmap: QPixmap | None = None):
        self._req += 1
        req = self._req
        self.source = res
        self.pixmap = pixmap
        self.copy_img_btn.setEnabled(pixmap is not None and not pixmap.isNull())
        self.speaker.stop()
        self._hide_popup()
        self.selbar.hide()
        self._sel_req += 1
        log.info("Showing result (%s source)", res.language)

        en = self.sections["english"]
        if res.language == "ja":
            self._set_japanese(res.text)
            self._set_ja_badges("from screenshot")
            en.badge.setText("translated")
            en.view.set_content("Translating…")
            src, dst, text = "ja", "en", flatten(res.text, "ja")
        else:
            en.view.set_content(res.text)
            en.badge.setText("from screenshot")
            self._set_japanese("")
            self._set_ja_badges("translated")
            for k in RENDER_MODE:
                self.sections[k].view.set_content("翻訳中… (translating)")
            src, dst, text = "en", "ja", flatten(res.text, "en")
        self.status.setText(f"OCR confidence {res.confidence:.0f}%")

        run_async(translate.translate, text, src, dst, self.cfg.translator,
                  on_done=lambda out: self._translated(req, src, out),
                  on_error=lambda msg: self._translate_failed(req, src, msg))

        if not self.isVisible() or not self._placed:
            self._place_near(anchor)
            self._placed = True
        self.show()
        self.raise_()
        self.activateWindow()

    def _set_ja_badges(self, text: str):
        for k in RENDER_MODE:
            self.sections[k].badge.setText(text)

    def _translated(self, req, src, out: str):
        if req != self._req:
            log.debug("Discarding stale translation")
            return
        if src == "ja":
            self.sections["english"].view.set_content(out)
        else:
            self._set_japanese(out)
        self.status.setText(self.status.text() + "  ·  translated")

    def _translate_failed(self, req, src, msg):
        if req != self._req:
            return
        log.error("Translation failed: %s", msg)
        text = f"(Translation failed: {msg})"
        if src == "ja":
            self.sections["english"].view.set_content(text)
        else:
            for k in RENDER_MODE:
                self.sections[k].view.set_content(text)
        self.status.setText("Translation failed — see terminal for details")

    def _set_japanese(self, text: str):
        self.ja_text = text
        try:
            self.ja_lines = japanese.tokenize(text) if text else []
        except Exception:
            log.exception("Japanese tokenizer failed; readings and hover lookup disabled")
            self.ja_lines = [[japanese.Token(line, "", line, "", "", False)] for line in text.split("\n")]
        for key, mode in RENDER_MODE.items():
            view = self.sections[key].view
            if isinstance(view, FuriganaView):
                if text:
                    view.set_lines(self.ja_lines)
                else:
                    view.set_content("")
                continue
            t, spans = japanese.render(self.ja_lines, mode)
            view.set_content(t, spans)
        self.play_btn.setEnabled(bool(text.strip()))

    def _place_near(self, anchor: QRect):
        scr = (QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()).availableGeometry()
        x = anchor.right() + 16
        if x + self.width() > scr.right():
            x = anchor.left() - self.width() - 16
        if x < scr.left():
            x = scr.right() - self.width() - 16
        y = min(max(anchor.top(), scr.top() + 10), scr.bottom() - self.height() - 40)
        self.move(x, max(y, scr.top()))

    # -- dictionary -------------------------------------------------------
    def _lookup(self, tok, rect: QRect):
        for sec in self.sections.values():
            if sec.view is not self.sender():
                sec.view.clear_hover()
        self._lookup_req += 1
        try:
            gram = grammar.to_html(grammar.describe(self.ja_lines, tok))
        except Exception:  # noqa: BLE001
            log.exception("Grammar analysis failed for %r", tok.surface)
            gram = ""
        self._lookup_ctx = {"id": self._lookup_req, "tok": tok, "rect": rect, "gram": gram,
                            "entries": None, "error": "", "kanji": "", "loading": True}
        self._render_popup()
        self.dictionary.lookup(self._lookup_req, tok.candidates())
        if any(kanji.is_kanji(c) for c in tok.surface + tok.base):
            self.dictionary.lookup_kanji(self._lookup_req, tok.surface if japanese.has_kanji(tok.surface)
                                         else tok.base)

    def _render_popup(self):
        c = self._lookup_ctx
        if c and self.isVisible():
            self.popup.show_info(c["tok"], c["rect"], c["gram"], c["entries"], c["error"], c["kanji"],
                                 c["loading"])

    def _lookup_done(self, req_id, query, entries, error):
        if not self._lookup_ctx or req_id != self._lookup_ctx["id"]:
            return
        self._lookup_ctx.update(entries=entries, error=error, loading=False)
        self._render_popup()

    def _kanji_done(self, req_id, infos):
        if not self._lookup_ctx or req_id != self._lookup_ctx["id"]:
            return
        self._lookup_ctx["kanji"] = kanji.to_html(infos, theme.ACCENT)
        self._render_popup()

    def _hide_popup(self):
        self.popup.hide()
        for sec in self.sections.values():
            sec.view.clear_hover()

    # -- selection translation ---------------------------------------------
    def _selection_changed(self, view: WordView):
        self._sel_view = view
        self._sel_timer.start()

    def _translate_selection(self):
        v = self._sel_view
        if v is None:
            return
        text = v.original_of_selection().strip()
        if not text or len(text) > 2000:
            return
        is_en = v is self.sections["english"].view
        src, dst = ("en", "ja") if is_en else ("ja", "en")
        if not is_en and v.toPlainText().startswith(("翻訳中", "(Translation failed")):
            return
        self._sel_req += 1
        req = self._sel_req
        self.sel_label.setText(f"<b>{html.escape(text)}</b> → <i style='color:gray'>translating…</i>")
        self._sel_result = ""
        self.selbar.show()
        log.info("Translating selection %s->%s: %s", src, dst, short(text))
        run_async(translate.translate, text, src, dst, self.cfg.translator,
                  on_done=lambda out: self._selection_done(req, text, dst, out),
                  on_error=lambda msg: self._selection_done(req, text, dst, None, msg))

    def _selection_done(self, req, text, dst, out, err=""):
        if req != self._sel_req:
            return
        if out is None:
            self.sel_label.setText(f"<b>{html.escape(text)}</b> → <span style='color:#d44'>"
                                   f"failed: {html.escape(err)}</span>")
            return
        self._sel_result = out
        extra = ""
        if dst == "ja":
            try:
                rom = japanese.render(japanese.tokenize(out), "romaji")[0]
                extra = f"<br><span style='color:gray'>{html.escape(rom)}</span>"
            except Exception:  # noqa: BLE001
                pass
        self.sel_label.setText(f"<b>{html.escape(text)}</b> → {html.escape(out)}{extra}")

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
    def _copy_image(self):
        if self.pixmap is None or self.pixmap.isNull():
            self.status.setText("No screenshot to copy")
            return
        copy_image(self.pixmap)
        self.status.setText("Copied screenshot to clipboard")

    def _escape(self):
        if self.popup.isVisible():
            self._hide_popup()
        else:
            self.hide()

    def _view_under_cursor(self):
        for sec in self.sections.values():
            v = sec.view
            if sec.isVisible() and v.spans:
                pos = v.viewport().mapFromGlobal(QCursor.pos())
                if v.viewport().rect().contains(pos):
                    return v
        return None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Shift and not ev.isAutoRepeat() \
                and self.isVisible():
            v = self._view_under_cursor()
            if v is not None:
                v.clear_hover()
                v.lookup_at(v.viewport().mapFromGlobal(QCursor.pos()))
        elif t == QEvent.Type.MouseButtonPress and self.popup.isVisible() \
                and any(obj is s.view.viewport() for s in self.sections.values()):
            self._hide_popup()
        return False

    def hideEvent(self, e):
        self._hide_popup()
        self.speaker.stop()
        super().hideEvent(e)
