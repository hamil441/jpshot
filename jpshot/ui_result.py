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
import re
import time

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QClipboard, QColor, QCursor, QFont, QGuiApplication, QKeySequence,
                           QPixmap, QShortcut, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from . import difficulty, features, grammar, japanese, kanji, lookupkey, patterns, pitch, theme, translate
from .furigana_view import FuriganaView
from .image_view import ImageView
from .config import ALL_SECTIONS
from .log import short
from .ocr import OcrResult, flatten
from .workers import run_async

log = logging.getLogger("jpshot.ui")

JP_FONTS = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic UI", "Meiryo", "Hiragino Sans",
            "Hiragino Kaku Gothic ProN", "MS Gothic", "IPAexGothic", "TakaoPGothic"]
SECTION_TITLES = {"english": "English", "japanese": "日本語", "furigana": "Furigana",
                  "hiragana": "ひらがな", "romaji": "Rōmaji"}
UNKNOWN_COLOR, KNOWN_COLOR = "#e8556d", "#8e9099"
CHIP_LABELS = {"english": "English\n英語", "japanese": "Japanese\n日本語", "furigana": "Furigana\nふりがな",
               "hiragana": "Hiragana\nひらがな", "romaji": "Rōmaji\nローマ字"}
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


def english_spans(text: str) -> list:
    """Word spans for the English row, so Shift-hover can look English words up."""
    spans = []
    for m in re.finditer(r"[A-Za-z][A-Za-z'’-]*[A-Za-z]|[A-Za-z]", text):
        w = m.group()
        start = japanese.u16len(text[:m.start()])
        tok = japanese.Token(w, "", w.lower(), w.lower(), "english", True)
        spans.append(japanese.Span(start, start + japanese.u16len(w), tok))
    return spans


# ---------------------------------------------------------------------------
class WordView(QTextEdit):
    """Read-only text. If it has word spans, holding Shift while hovering looks words up."""

    lookup_requested = Signal(object, QRect)  # Token, global rect of the word
    play_requested = Signal(object, str)      # Token, "from" | "phrase"

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
        self.hover_lookup = False   # a color scheme is on (re-applied when content changes)
        self._colored = False
        self.color_fn = grammar.color_for

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
                col = self.color_fn(span.token)
                if not col:
                    continue
                if isinstance(col, list):   # one color per sound (pitch mode)
                    cur.setPosition(span.start)
                    cur.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
                    pos = span.start
                    for m, c in zip(pitch.morae(cur.selectedText()), col):
                        n = japanese.u16len(m)
                        cur.setPosition(pos)
                        cur.setPosition(pos + n, QTextCursor.MoveMode.KeepAnchor)
                        fmt = QTextCharFormat()
                        fmt.setForeground(QColor(c))
                        cur.mergeCharFormat(fmt)
                        pos += n
                    continue
                cur.setPosition(span.start)
                cur.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(col))
                cur.mergeCharFormat(fmt)
        cur.endEditBlock()
        self._colored = on

    def refresh_colors(self):
        if self._colored:
            self.set_colors(False)
            self.set_colors(True)

    def original_of_selection(self) -> str:
        """Selected text; in a Japanese row, mapped back to the original words."""
        c = self.textCursor()
        a, b = c.selectionStart(), c.selectionEnd()
        if a == b:
            return ""
        if not self.spans or self.spans[0].token.pos == "english":
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
        self.setExtraSelections(getattr(self, "_marks", []))

    def mark_tokens(self, ids: set[int]):
        """Underline the words of a grammar pattern."""
        marks = []
        for sp in self.spans:
            if id(sp.token) in ids:
                sel = QTextEdit.ExtraSelection()
                fmt = QTextCharFormat()
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
                fmt.setUnderlineColor(QColor(80, 160, 255))
                fmt.setBackground(QColor(80, 160, 255, 45))
                sel.format = fmt
                c = QTextCursor(self.document())
                c.setPosition(sp.start)
                c.setPosition(sp.end, QTextCursor.MoveMode.KeepAnchor)
                sel.cursor = c
                marks.append(sel)
        self._marks = marks
        self.setExtraSelections(marks)

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
        self.setExtraSelections(getattr(self, "_marks", []) + [sel])
        a = QTextCursor(self.document())
        a.setPosition(span.start)
        b = QTextCursor(self.document())
        b.setPosition(span.end)
        r = self.cursorRect(a).united(self.cursorRect(b))
        glob = QRect(self.viewport().mapToGlobal(r.topLeft()), r.size())
        log.debug("Hover %r (base %r, reading %r)", span.token.surface, span.token.base, span.token.reading)
        self.lookup_requested.emit(span.token, glob)

    def contextMenuEvent(self, e):
        span = self.span_at(self.viewport().mapFromGlobal(e.globalPos()))
        if span is None or span.token.pos == "english":
            return super().contextMenuEvent(e)
        from PySide6.QtGui import QAction

        menu = self.createStandardContextMenu()
        first = menu.actions()[0] if menu.actions() else None
        a1 = QAction(f"▶ Play from “{span.token.surface}”", menu)
        a2 = QAction("▶ Play this phrase", menu)
        menu.insertAction(first, a1)
        menu.insertAction(first, a2)
        if first is not None:
            menu.insertSeparator(first)
        chosen = menu.exec(e.globalPos())
        if chosen is a1:
            self.play_requested.emit(span.token, "from")
        elif chosen is a2:
            self.play_requested.emit(span.token, "phrase")

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if (e.modifiers() & lookupkey.modifier()) \
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
    play_requested = Signal()
    link_requested = Signal(str)

    def _link(self, href: str):
        if href == "play":
            self.play_requested.emit()
        else:
            self.link_requested.emit(href)

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
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.label.linkActivated.connect(self._link)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(self.label)

    def _head(self, tok) -> str:
        if tok.pos == "english":
            return f"<span style='font-size:20pt'><b>{html.escape(tok.surface)}</b></span>"
        h = (f"<a href='play' style='text-decoration:none'>🔊</a>&nbsp;"
             f"<span style='font-size:20pt'><b>{html.escape(tok.surface)}</b></span>")
        if tok.reading and tok.reading != tok.surface:
            h += f"&nbsp;&nbsp;<span style='font-size:13pt;color:{theme.ACCENT}'>{html.escape(tok.reading)}</span>"
        h += f"&nbsp;&nbsp;<span style='color:gray'>{html.escape(japanese.romaji_of(tok))}</span>"
        if tok.base and tok.base != tok.surface:
            h += f"<br><span style='color:gray'>dictionary form: {html.escape(tok.base)}</span>"
        return h

    def show_info(self, tok, rect: QRect, gram_html: str, entries, error: str, kanji_html: str,
                  loading: bool, extra_html: str = "", after_html: str = ""):
        body = self._head(tok) + extra_html + gram_html
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
        body += after_html
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
    mine_requested = Signal()

    def __init__(self, cfg, dictionary, speaker, known=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.cfg, self.dictionary, self.speaker = cfg, dictionary, speaker
        if known is None:
            from .known import KnownWords
            known = KnownWords()
        self.known = known
        from .history import History
        self.history = History()
        self._pending_capture = None
        self._history_window = None
        self.setWindowTitle("JPShot")
        self.setStyleSheet(CSS)
        self.resize(940, 640)

        self.source: OcrResult | None = None
        self.pixmap: QPixmap | None = None
        self.ja_text = ""
        self.ja_lines: list[list[japanese.Token]] = []
        self._req = 0
        self._lookup_req = 0
        self._lookup_ctx = None
        self._placed = False
        self._pitch_map: dict = {}
        self._sel_req = 0
        self._diff_req = 0
        self.difficulty = None
        self._sel_text = ""
        self._sel_view: WordView | None = None
        self._sel_timer = QTimer(self, singleShot=True, interval=450)
        self._sel_timer.timeout.connect(self._translate_selection)

        self.popup = DictionaryPopup()
        self.popup.play_requested.connect(self._play_word)
        self.popup.link_requested.connect(self._popup_link)

        # sections, stacked in a splitter so rows can be resized
        self.sections: dict[str, Section] = {}
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        for key in ALL_SECTIONS:
            sec = Section(key, self._font_for(key))
            sec.view.lookup_requested.connect(self._lookup)
            sec.view.play_requested.connect(self._play_part)
            sec.view.viewport().installEventFilter(self)
            sec.view.selectionChanged.connect(lambda v=sec.view: self._selection_changed(v))
            self.sections[key] = sec
            self.splitter.addWidget(sec)

        self.status = QLabel()
        self.status.setObjectName("muted")
        hint = QLabel()
        self.hint = hint
        self._update_hint()
        hint.setObjectName("muted")
        foot = QHBoxLayout()
        foot.addWidget(self.status, 1)
        foot.addWidget(hint)

        self.legend = QLabel()
        self.legend.setObjectName("muted")
        self.legend.setWordWrap(True)
        self.pattern_bar = QLabel()
        self.pattern_bar.setWordWrap(True)
        self.pattern_bar.setTextFormat(Qt.TextFormat.RichText)
        self.pattern_bar.linkActivated.connect(self._pattern_clicked)
        self.pattern_bar.hide()
        self.pattern_matches: list = []
        self._marked_pattern = -1

        # screenshot on the left, text on the right
        self.image_view = ImageView()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._build_selection_bar())
        rl.addWidget(self.splitter, 1)
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.addWidget(self.image_view)
        self.hsplit.addWidget(right)
        self.hsplit.setStretchFactor(0, 2)
        self.hsplit.setStretchFactor(1, 3)
        self.hsplit.setSizes([360, 560])

        root = QVBoxLayout(self)
        root.addLayout(self._build_toolbar())
        root.addWidget(self.legend)
        root.addWidget(self.pattern_bar)
        root.addWidget(self.hsplit, 1)
        root.addWidget(self._build_audio())
        root.addLayout(foot)

        en_view = self.sections["english"].view
        en_view.set_content = self._english_setter(en_view)
        # the English box is editable: clicking a Japanese box (or Ctrl+Enter) re-translates it
        en_view.setReadOnly(False)
        en_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        en_view.setToolTip("Edit the English — click a Japanese box (or press Ctrl+Enter) to update them")
        self._en_dirty = False
        self._en_programmatic = False
        en_view.textChanged.connect(self._english_edited)
        QShortcut(QKeySequence("Ctrl+Return"), en_view, self._apply_english_edit,
                  context=Qt.ShortcutContext.WidgetShortcut)
        fv = self.sections["furigana"].view
        if isinstance(fv, FuriganaView):
            fv.set_known_kanji(self.known.known_kanji(), bool(self.cfg.furigana_unknown_only))
        self._apply_section_visibility()
        self._apply_color_mode()
        self._update_image_visibility()
        self.apply_features()
        dictionary.finished.connect(self._lookup_done)
        dictionary.kanji_finished.connect(self._kanji_done)
        dictionary.difficulty_finished.connect(self._difficulty_done)
        dictionary.english_finished.connect(self._english_done)
        dictionary.examples_finished.connect(self._examples_done)
        speaker.state_changed.connect(self._speaker_state)
        QApplication.instance().installEventFilter(self)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence("["), self, lambda: self.speed.setValue(self.speed.value() - 10))
        QShortcut(QKeySequence("]"), self, lambda: self.speed.setValue(self.speed.value() + 10))
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._copy_image)
        QShortcut(QKeySequence("W"), self, self._play_word)
        QShortcut(QKeySequence("K"), self, self._toggle_known)
        QShortcut(QKeySequence("Ctrl+E"), self, lambda: self.feat("ask") and self.ask_btn.isEnabled() and self.open_ask())
        QShortcut(QKeySequence("Ctrl+H"), self, lambda: self.feat("history") and self.open_history())
        QShortcut(QKeySequence("Ctrl+,"), self, self.settings_requested.emit)
        QShortcut(QKeySequence("Ctrl+M"), self,
                  lambda: self.feat("anki") and self.mine_btn.isEnabled() and self.mine_requested.emit())

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
            b.setText(CHIP_LABELS[key])
            b.setCheckable(True)
            b.setToolTip(f"Show {SECTION_TITLES[key]}  (Alt+{i + 1})\n"
                         "Ctrl+click to show several boxes at once")
            b.setShortcut(QKeySequence(f"Alt+{i + 1}"))
            b.clicked.connect(lambda _=False, k=key: self._chip_clicked(k))
            self.chips[key] = b
            bar.addWidget(b)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        bar.addWidget(sep)
        self.color_sep = sep
        self.color_btns: dict[str, QToolButton] = {}
        for mode, label, key, tip in (
                ("grammar", "Grammar", "Alt+G", "Color words by part of speech"),
                ("pitch", "Pitch", "Alt+P", "Color words by pitch accent: blue heiban, red atamadaka, "
                                            "orange nakadaka, green odaka"),
                ("difficulty", "Difficulty", "Alt+D", "Color words from easy (green) to hard (red)"),
                ("known", "Known", "Alt+N", "Highlight words you don't know yet (K marks a word known)")):
            b = QToolButton()
            b.setObjectName("chip")
            b.setText(label)
            b.setCheckable(True)
            b.setToolTip(f"{tip}  ({key})\nOnly one coloring at a time; click again to turn it off")
            b.setShortcut(QKeySequence(key))
            b.clicked.connect(lambda _=False, m=mode: self._color_clicked(m))
            self.color_btns[mode] = b
            bar.addWidget(b)
        self.diff_label = QLabel()
        self.diff_label.setTextFormat(Qt.TextFormat.RichText)
        bar.addSpacing(8)
        bar.addWidget(self.diff_label)
        self.known_label = QLabel()
        self.known_label.setTextFormat(Qt.TextFormat.RichText)
        bar.addSpacing(6)
        bar.addWidget(self.known_label)
        bar.addStretch()
        hist = QToolButton()
        self.hist_btn = hist
        hist.setText("📜")
        hist.setToolTip("History of your captures, and words you keep seeing  (Ctrl+H)")
        hist.clicked.connect(self.open_history)
        bar.addWidget(hist)
        self.ask_btn = QToolButton()
        self.ask_btn.setText("❓ Ask")
        self.ask_btn.setToolTip("Ask a tutor about this sentence  (Ctrl+E)")
        self.ask_btn.setEnabled(False)
        self.ask_btn.clicked.connect(self.open_ask)
        bar.addWidget(self.ask_btn)
        self.mine_btn = QToolButton()
        self.mine_btn.setText("⛏ Mine")
        self.mine_btn.setToolTip("Make an Anki card from this capture  (Ctrl+M)")
        self.mine_btn.setEnabled(False)
        self.mine_btn.clicked.connect(self.mine_requested.emit)
        bar.addWidget(self.mine_btn)
        self.copy_img_btn = QToolButton()
        self.copy_img_btn.setText("Copy image")
        self.copy_img_btn.setToolTip("Copy the screenshot to the clipboard  (Ctrl+Shift+C)")
        self.copy_img_btn.setEnabled(False)
        self.copy_img_btn.clicked.connect(self._copy_image)
        bar.addWidget(self.copy_img_btn)
        self.image_btn = QToolButton()
        self.image_btn.setText("🖼")
        self.image_btn.setCheckable(True)
        self.image_btn.setChecked(bool(self.cfg.show_image))
        self.image_btn.setToolTip("Show the screenshot beside the text  (Ctrl+I)\n"
                                  "Scroll to zoom · drag to move · double-click to fit")
        self.image_btn.setShortcut(QKeySequence("Ctrl+I"))
        self.image_btn.toggled.connect(self._image_toggled)
        bar.addWidget(self.image_btn)
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
        say = QToolButton()
        say.setText("🔊")
        say.setAutoRaise(True)
        say.setToolTip("Hear the highlighted Japanese")
        say.clicked.connect(self._play_selection)
        lay.addWidget(say)
        copy = QToolButton()
        copy.setText("Copy")
        copy.setAutoRaise(True)
        copy.setToolTip("Copy this translation")
        copy.clicked.connect(lambda: self._sel_result and copy_text(self._sel_result))
        lay.addWidget(copy)
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
        self.shadow_btn = QToolButton()
        self.shadow_btn.setText("🎙 Shadow")
        self.shadow_btn.setToolTip("Shadowing practice: record yourself and compare with the voice")
        self.shadow_btn.setEnabled(False)
        self.shadow_btn.clicked.connect(self.open_shadow)
        lay.addWidget(self.shadow_btn)
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
    def _image_toggled(self, on: bool):
        self.cfg.show_image = on
        self.cfg.save()
        self._update_image_visibility()

    def _update_image_visibility(self):
        has = self.pixmap is not None and not self.pixmap.isNull()
        self.image_view.setVisible(bool(self.cfg.show_image) and has and self.feat("image"))
        if self.image_view.isVisible():
            self.image_view.fit()

    # -- selectable features ------------------------------------------------
    def feat(self, key: str) -> bool:
        return features.enabled(self.cfg, key)

    def apply_features(self):
        """Show only what's switched on in ⚙ Settings → Selectable features."""
        color_keys = {"grammar": "grammar", "pitch": "pitch", "difficulty": "difficulty", "known": "known"}
        any_color = False
        for mode, b in self.color_btns.items():
            on = self.feat(color_keys[mode])
            b.setVisible(on)
            any_color |= on
        self.color_sep.setVisible(any_color)
        if self.cfg.color_mode in color_keys and not self.feat(color_keys[self.cfg.color_mode]):
            self.cfg.color_mode = "none"
            self._apply_color_mode()
        self.known_label.setVisible(self.feat("known"))
        self.pattern_bar.setVisible(self.feat("grammar") and bool(self.pattern_matches))
        self.ask_btn.setVisible(self.feat("ask"))
        self.mine_btn.setVisible(self.feat("anki"))
        self.hist_btn.setVisible(self.feat("history"))
        self.shadow_btn.setVisible(self.feat("shadow"))
        self.image_btn.setVisible(self.feat("image"))
        if not self.feat("selection"):
            self.selbar.hide()
        self._update_image_visibility()

    def _update_hint(self):
        self.hint.setText(f"Hold <b>{lookupkey.name()}</b> over a Japanese word to look it up")

    def update_theme_button(self):
        dark = theme.is_dark(self.cfg.theme)
        self.theme_btn.setText("☀" if dark else "☾")

    def apply_settings(self):
        """Re-read fonts, sections and theme from the config (after the settings dialog)."""
        for key, sec in self.sections.items():
            sec.view.setFont(self._font_for(key))
        self._apply_section_visibility()
        self._apply_color_mode()
        lookupkey.set_key(self.cfg.lookup_key)
        self._update_hint()
        self.known_changed()
        self.apply_features()
        self.update_theme_button()
        self.setStyleSheet("")
        self.setStyleSheet(CSS)

    def _color_clicked(self, mode: str):
        self.cfg.color_mode = "none" if self.cfg.color_mode == mode else mode
        self.cfg.save()
        self._hide_popup()
        self._apply_color_mode()
        log.info("Word coloring: %s", self.cfg.color_mode)

    def _color_fn(self, row: str = "japanese"):
        mode = self.cfg.color_mode
        if mode == "pitch":
            if row == "hiragana":
                return lambda tok: pitch.mora_colors(self._pitch_map.get(id(tok)))
            if row == "furigana":
                return lambda tok: None        # readings are colored per sound; kanji stay plain
            return pitch.word_color
        if mode == "difficulty":
            return lambda tok: difficulty.word_color(self.difficulty, tok)
        if mode == "known":
            return self._known_color
        return grammar.color_for

    def _apply_color_mode(self):
        mode = self.cfg.color_mode if self.cfg.color_mode in ("grammar", "pitch", "difficulty", "known") else "none"
        for m, b in self.color_btns.items():
            b.setChecked(m == mode)
        self._update_legend()
        self._pitch_map = pitch.sentence_highs(self.ja_lines) if mode == "pitch" else {}
        on = mode != "none"
        for key, sec in self.sections.items():
            if key in RENDER_MODE:
                sec.view.color_fn = self._color_fn(key)
                if isinstance(sec.view, FuriganaView):
                    sec.view.pitch_fn = (lambda tok: self._pitch_map.get(id(tok))) if mode == "pitch" else None
                sec.view.hover_lookup = on
                sec.view.set_colors(False)
                sec.view.set_colors(on)

    def _update_legend(self):
        mode = self.cfg.color_mode
        shown = set(self.cfg.sections)
        if mode == "pitch":
            text = pitch.legend_html(shown)
        elif mode == "grammar":
            text = grammar.legend_html()
        elif mode == "difficulty":
            text = difficulty.legend_html()
        elif mode == "known":
            text = (f"<span style='color:{UNKNOWN_COLOR}'>■</span> new to you  "
                    f"<span style='color:{KNOWN_COLOR}'>■</span> known  ·  "
                    f"<span style='color:gray'>hold Shift on a word and press K to mark it known/unknown "
                    f"· {self.known.total()} known words</span>")
        else:
            text = ""
        self.legend.setText(text)
        self.legend.setToolTip(pitch.legend_tooltip() if mode == "pitch" else "")
        self.legend.setVisible(bool(text))

    def _apply_section_visibility(self):
        shown = set(self.cfg.sections)
        for key, chip in self.chips.items():
            chip.blockSignals(True)
            chip.setChecked(key in shown)
            chip.blockSignals(False)
            self.sections[key].setVisible(key in shown)
        if hasattr(self, "legend"):
            self._update_legend()

    def _chip_clicked(self, key: str):
        """Click: show only this box. Ctrl/Shift+click: add or remove it from what's shown."""
        mods = QApplication.keyboardModifiers()
        multi = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        if multi:
            shown = [k for k in ALL_SECTIONS if self.chips[k].isChecked()]
        else:
            shown = [key]
        self.cfg.sections = shown or [key]
        self.cfg.save()
        self._apply_section_visibility()
        self._hide_popup()
        log.debug("Boxes shown: %s", self.cfg.sections)

    # -- showing a new capture -------------------------------------------
    def show_result(self, res: OcrResult, anchor: QRect, pixmap: QPixmap | None = None):
        self._req += 1
        req = self._req
        self.source = res
        self.pixmap = pixmap
        self.image_view.set_pixmap(pixmap)
        self._update_image_visibility()
        self.copy_img_btn.setEnabled(pixmap is not None and not pixmap.isNull())
        self.mine_btn.setEnabled(True)
        self.ask_btn.setEnabled(True)
        self._sel_text = ""
        self._lookup_ctx = None
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
        from .history import Capture
        self._pending_capture = (req, Capture(id=time.strftime("%Y%m%d-%H%M%S"), time=time.time(),
                                              language=res.language, source=res.text, japanese="", english=""))

        run_async(translate.translate, text, src, dst, self.cfg.translator,
                  on_done=lambda out: self._translated(req, src, out),
                  on_error=lambda msg: self._translate_failed(req, src, msg))

        if not self.isVisible() or not self._placed:
            self._place_near(anchor)
            self._placed = True
        self.show()
        self.raise_()
        self.activateWindow()

    def _english_setter(self, view):
        """English text gets word spans (for lookups) unless it's a status message."""
        base = WordView.set_content.__get__(view)

        def setter(text: str, spans=None):
            is_message = text.startswith(("Translating", "(Translation failed"))
            self._en_programmatic = True
            try:
                base(text, None if is_message else english_spans(text))
            finally:
                self._en_programmatic = False
            self._en_dirty = False
        return setter

    def _english_edited(self):
        if self._en_programmatic:
            return
        en = self.sections["english"]
        if not self._en_dirty:
            self._en_dirty = True
            en.badge.setText("edited — click a Japanese box to update")
        en.view.spans = []          # word positions are stale until re-applied

    def _apply_english_edit(self):
        en = self.sections["english"]
        text = en.view.toPlainText().strip()
        if not self._en_dirty or not text:
            return
        self._en_dirty = False
        en.badge.setText("your edit")
        en.view.spans = english_spans(en.view.toPlainText())
        self._req += 1
        req = self._req
        for k in RENDER_MODE:
            self.sections[k].view.set_content("翻訳中… (translating)")
        self._set_ja_badges("translated from your English")
        log.info("Re-translating edited English: %s", short(text))
        run_async(translate.translate, flatten(text, "en"), "en", "ja", self.cfg.translator,
                  on_done=lambda out: self._translated(req, "en", out),
                  on_error=lambda msg: self._translate_failed(req, "en", msg))

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
        self._save_pending_capture(req)

    def _translate_failed(self, req, src, msg):
        if req != self._req:
            return
        self._save_pending_capture(req)
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
        if self.cfg.color_mode == "pitch":
            self._pitch_map = pitch.sentence_highs(self.ja_lines)
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
        self.shadow_btn.setEnabled(bool(text.strip()))
        if self.feat("known"):
            self._update_known_badge()
        if self.feat("grammar"):
            self._update_patterns()
        else:
            self.pattern_matches = []
            self.pattern_bar.hide()
        self._diff_req += 1
        self.difficulty = None
        if text.strip():   # the sentence rating is always shown
            self.diff_label.setText("<span style='color:gray'>rating…</span>")
            self.dictionary.estimate_difficulty(self._diff_req, self.ja_lines)
        else:
            self.diff_label.setText("")

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
        if tok.pos == "english":
            self._lookup_english(tok, rect)
            return
        self._lookup_japanese(tok, rect)

    def _lookup_english(self, tok, rect: QRect):
        for sec in self.sections.values():
            if sec.view is not self.sender():
                sec.view.clear_hover()
        self._lookup_req += 1
        self._lookup_ctx = {"id": self._lookup_req, "tok": tok, "rect": rect, "gram": "",
                            "extra": "<div style='color:gray'>Finding the Japanese word…</div>",
                            "entries": None, "error": "", "kanji": "", "loading": True,
                            "english": tok.surface}
        self._render_popup()
        self.dictionary.lookup_english(self._lookup_req, tok.surface, self.cfg.translator)

    def _english_done(self, req_id, word, entries, error):
        c = self._lookup_ctx
        if not c or req_id != c["id"]:
            return
        if error or not entries:
            c.update(entries=[], error=error, loading=False,
                     extra=f"<div style='color:gray'>No Japanese word found for “{html.escape(word)}”.</div>")
            self._render_popup()
            return
        e = entries[0]
        try:
            toks = [t for line in japanese.tokenize(e.word) for t in line if t.surface.strip()]
        except Exception:  # noqa: BLE001
            toks = []
        if len(toks) == 1:
            jt = toks[0]
        else:
            jt = japanese.Token(e.word, "", e.word, e.word, toks[0].pos if toks else "名詞", True)
        if e.reading and (japanese.has_kanji(jt.surface) or not jt.reading):
            jt.reading = japanese.kata_to_hira(e.reading)
        extra = f"<div style='color:gray'>“{html.escape(word)}” in Japanese:</div>" + \
            (pitch.pattern_html(jt) if self.feat("pitch") else "")
        others = [x.word + (f" ({x.reading})" if x.reading and x.reading != x.word else "") for x in entries[1:4]]
        if others:
            extra += f"<div style='color:gray;font-size:9pt'>also: {html.escape('、'.join(others))}</div>"
        gram = ""
        if self.feat("grammar"):
            try:
                gram = grammar.to_html(grammar.describe([[jt]], jt))
            except Exception:  # noqa: BLE001
                gram = ""
        from . import conjugate
        forms = conjugate.table_html(conjugate.conjugations(jt.base, jt.ctype, jt.pos)) if self.feat("examples") else ""
        c.update(tok=jt, gram=gram, extra=extra, entries=entries[:1], error="", loading=False, forms=forms)
        if self.feat("examples"):
            self.dictionary.examples(req_id, e.word)
        self._render_popup()
        if self.feat("kanji") and any(kanji.is_kanji(ch) for ch in jt.surface):
            self.dictionary.lookup_kanji(req_id, jt.surface, [e.word])

    def _lookup_japanese(self, tok, rect: QRect):
        for sec in self.sections.values():
            if sec.view is not self.sender():
                sec.view.clear_hover()
        self._lookup_req += 1
        gram = ""
        if self.feat("grammar"):
            try:
                gram = grammar.to_html(grammar.describe(self.ja_lines, tok)) + self._patterns_html(tok)
            except Exception:  # noqa: BLE001
                log.exception("Grammar analysis failed for %r", tok.surface)
        extra = (self._known_line(tok) if self.feat("known") else "") + \
            (pitch.pattern_html(tok) if self.feat("pitch") else "")
        lvl = difficulty.word_level(self.difficulty, tok) if self.feat("difficulty") else ""
        if lvl:
            extra += f"<div style='color:gray;font-size:9pt'>word difficulty ≈{lvl}</div>"
        forms = ""
        if self.feat("examples"):
            from . import conjugate
            forms = conjugate.table_html(conjugate.conjugations(tok.base, tok.ctype, tok.pos))
            self.dictionary.examples(self._lookup_req, tok.base or tok.surface)
        self._lookup_ctx = {"id": self._lookup_req, "tok": tok, "rect": rect, "gram": gram, "extra": extra,
                            "forms": forms,
                            "entries": None, "error": "", "kanji": "", "loading": True}
        self._render_popup()
        self.dictionary.lookup(self._lookup_req, tok.candidates())
        if self.feat("kanji") and any(kanji.is_kanji(c) for c in tok.surface + tok.base):
            self.dictionary.lookup_kanji(self._lookup_req, tok.surface if japanese.has_kanji(tok.surface)
                                         else tok.base, tok.candidates())

    # -- known words --------------------------------------------------------
    def _known_color(self, tok):
        if not self.known.counts(tok):
            return None
        return KNOWN_COLOR if self.known.is_known(tok) else UNKNOWN_COLOR

    def _update_known_badge(self):
        if not self.ja_text.strip():
            self.known_label.setText("")
            return
        unknown = self.known.unknown_words(self.ja_lines)
        n = len(unknown)
        if n == 0:
            text = "<span style='color:#2fb383'>all known</span>"
        elif n == 1:
            text = "<span style='color:#2fb383'><b>i+1</b> ✓</span>"
        else:
            text = f"<span style='color:gray'>{n} new</span>"
        self.known_label.setText(text)
        tip = ("i+1: exactly one new word — a great sentence to mine.\n" if n == 1 else "")
        self.known_label.setToolTip(tip + ("New to you: " + "、".join(t.base for t in unknown[:15])
                                           if unknown else "You know every word in this sentence"))

    def known_changed(self):
        """Known words changed (sync or K): refresh badge, colors, furigana and legend."""
        self._update_known_badge()
        fv = self.sections["furigana"].view
        if isinstance(fv, FuriganaView):
            fv.set_known_kanji(self.known.known_kanji(), bool(self.cfg.furigana_unknown_only))
        if self.cfg.color_mode == "known":
            for key, sec in self.sections.items():
                if key in RENDER_MODE:
                    sec.view.refresh_colors()
            self._update_legend()

    def _toggle_known(self):
        if not self.feat("known"):
            return
        c = self._lookup_ctx
        if not c or not self.popup.isVisible() or c["tok"].pos == "english":
            return
        state = self.known.toggle(c["tok"])
        self.status.setText(f"Marked {c['tok'].base} as {'known' if state else 'new'}")
        c["extra"] = self._known_line(c["tok"]) + c.get("extra", "").split("<!--known-->", 1)[-1]
        self._render_popup()
        self.known_changed()

    def _known_line(self, tok) -> str:
        if not self.known.counts(tok):
            return "<!--known-->"
        if self.known.is_known(tok):
            link = "<a href='known' style='color:#2fb383;text-decoration:none'>✓ known</a>"
        else:
            link = "<a href='known' style='color:#e8556d;text-decoration:none'>＋ mark as known</a>"
        return f"<div style='font-size:9pt'>{link} <span style='color:gray'>(K)</span></div><!--known-->"

    def _difficulty_done(self, req_id, d):
        if req_id != self._diff_req:
            return
        self.difficulty = d
        self._remember_difficulty(d)
        if d is None:
            self.diff_label.setText("")
            return
        self.diff_label.setText(f"<span style='color:{d.color}'><b>{d.jlpt}</b> {d.stars}</span>")
        if self.cfg.color_mode == "difficulty":
            for key, sec in self.sections.items():
                if key in RENDER_MODE:
                    sec.view.refresh_colors()
        new = len(self.known.unknown_words(self.ja_lines))
        personal = (f"\nFor you: {new} word{'s' if new != 1 else ''} you haven't marked known"
                    if self.known.total() else "")
        self.diff_label.setToolTip(f"Estimated difficulty: {d.label} (≈JLPT {d.jlpt})\n• "
                                   + "\n• ".join(d.reasons) + personal)

    def _examples_done(self, req_id, examples):
        c = self._lookup_ctx
        if not c or req_id != c["id"] or not examples:
            return
        rows = "".join(f"<div style='margin-left:6px'>{html.escape(jp)}<br>"
                       f"<span style='color:gray;font-size:9pt'>{html.escape(en)}</span></div>" for jp, en in examples)
        c["examples"] = f"<div style='margin-top:6px'><b>Examples</b></div>{rows}"
        self._render_popup()

    def _render_popup(self):
        c = self._lookup_ctx
        if c and self.isVisible():
            self.popup.show_info(c["tok"], c["rect"], c["gram"], c["entries"], c["error"], c["kanji"],
                                 c["loading"], c.get("extra", ""), c.get("forms", "") + c.get("examples", ""))

    def _lookup_done(self, req_id, query, entries, error):
        if not self._lookup_ctx or req_id != self._lookup_ctx["id"]:
            return
        self._lookup_ctx.update(entries=entries, error=error, loading=False)
        self._render_popup()

    def _kanji_done(self, req_id, payload):
        if not self._lookup_ctx or req_id != self._lookup_ctx["id"]:
            return
        infos = payload["infos"]
        self._kanji_infos = {k.char: k for k in infos}
        for k in infos:
            if k.svg and not k.image_path:
                try:
                    k.image_path = kanji.render_png(k)
                except Exception:  # noqa: BLE001
                    log.exception("Could not draw kanji %s", k.char)
        self._lookup_ctx["kanji"] = kanji.to_html(infos, theme.ACCENT, payload.get("word", ""),
                                                  payload.get("word_story", ""), payload.get("hint", False))
        self._render_popup()

    def _hide_popup(self):
        self.popup.hide()
        for sec in self.sections.values():
            sec.view.clear_hover()

    # -- selection translation ---------------------------------------------
    def _selection_changed(self, view: WordView):
        if not self.feat("selection"):
            return
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
        self._sel_text = text
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

    # -- mining -----------------------------------------------------------
    def mining_data(self) -> dict:
        """Everything the Mine dialog can put on a card."""
        lines = self.ja_lines
        d = {
            "japanese": self.ja_text,
            "furigana": japanese.anki_furigana(lines) if lines else "",
            "hiragana": japanese.render(lines, "hiragana")[0] if lines else "",
            "romaji": japanese.render(lines, "romaji")[0] if lines else "",
            "english": self.sections["english"].view.toPlainText(),
            "selection": self._sel_text,
            "selection_translation": self._sel_result if self._sel_text else "",
            "word": "", "word_furigana": "", "word_reading": "", "word_meaning": "", "word_pos": "",
            "sentence_cloze": "", "notes": "", "dictionary": self.dictionary,
            "difficulty": self.difficulty.summary() if self.difficulty else "",
            "difficulty_tag": f"difficulty::{self.difficulty.jlpt}" if self.difficulty else "",
            "pixmap": self.pixmap,
            "audio_text": flatten(self.ja_text, "ja"),
            "speed": self._speed_value(),
        }
        from .mine import word_fields

        c = self._lookup_ctx
        if c:
            tok = c["tok"]
            entries = c.get("entries") or []
            if entries:
                d.update(word_fields(tok.base or tok.surface, entries))
            else:
                d["word"] = tok.base or tok.surface
                d["word_reading"] = tok.reading
            surface = tok.surface
        elif self._sel_text and len(self._sel_text) <= 12:
            # no word looked up: use a short highlighted bit of text as the word
            d["word"] = self._sel_text
            surface = self._sel_text
        else:
            surface = ""
        if surface and surface in self.ja_text:
            d["sentence_cloze"] = self.ja_text.replace(surface, "＿＿", 1)
        return d

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

    def _popup_link(self, href: str):
        if href == "known":
            self._toggle_known()
        elif href.startswith("strokes:"):
            self._show_strokes(href.split(":", 1)[1])
        elif href.startswith("pattern:"):
            self._show_pattern(href.split(":", 1)[1])

    def _show_strokes(self, ch: str):
        from . import strokes

        info = getattr(self, "_kanji_infos", {}).get(ch)
        if info is None or not info.svg:
            self.status.setText(f"No stroke data for {ch}")
            return
        try:
            win = strokes.open_window(ch, info.svg, info.keyword or (info.meanings[0] if info.meanings else ""))
        except Exception:  # noqa: BLE001
            log.exception("Stroke-order window failed for %s", ch)
            return
        self._stroke_windows = [w for w in getattr(self, "_stroke_windows", []) if w.isVisible()] + [win]

    def _show_pattern(self, pid: str):
        self._pattern_clicked(f"p:{pid}")

    # -- history -------------------------------------------------------------
    def _save_pending_capture(self, req):
        if not self._pending_capture or self._pending_capture[0] != req:
            return
        if not self.feat("history"):
            self._pending_capture = None
            return
        cap = self._pending_capture[1]
        self._pending_capture = None
        cap.japanese = self.ja_text
        en = self.sections["english"].view.toPlainText()
        cap.english = "" if en.startswith(("Translating", "(Translation failed")) else en
        cap.words = [t.base for line in self.ja_lines for t in line if self.known.counts(t)]
        try:
            self.history.add(cap, self.pixmap)
        except Exception:  # noqa: BLE001
            log.exception("Could not save capture to history")
        if self._history_window is not None and self._history_window.isVisible():
            self._history_window.refresh()

    def _remember_difficulty(self, d):
        """Store the difficulty on the latest history entry once it's known (best effort)."""
        if d is None:
            return
        try:
            caps = self.history.all()
            if caps and caps[0].japanese == self.ja_text and not caps[0].difficulty:
                import json
                from dataclasses import asdict
                lines = self.history.index.read_text(encoding="utf-8").splitlines()
                last = json.loads(lines[-1])
                last["difficulty"] = d.jlpt
                lines[-1] = json.dumps(last, ensure_ascii=False)
                self.history.index.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def open_history(self):
        from .history import HistoryWindow

        if self._history_window is None:
            self._history_window = HistoryWindow(self.history, self.known.is_known_word)
            self._history_window.open_capture.connect(self.show_saved)
            self._history_window.mark_known.connect(lambda w: (self.known.mark_word(w), self.known_changed()))
        self._history_window.refresh()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def show_saved(self, cap):
        """Re-open a capture from history (no OCR or translation needed)."""
        self._req += 1
        self._pending_capture = None
        pm = self.history.pixmap(cap)
        self.pixmap = pm
        self.copy_img_btn.setEnabled(pm is not None)
        self.image_view.set_pixmap(pm)
        self._update_image_visibility()
        self.mine_btn.setEnabled(True)
        self.ask_btn.setEnabled(True)
        self.speaker.stop()
        self._hide_popup()
        self.selbar.hide()
        self._sel_text = ""
        self._lookup_ctx = None
        en = self.sections["english"]
        en.view.set_content(cap.english)
        en.badge.setText("from history")
        self._set_japanese(cap.japanese)
        self._set_ja_badges("from history")
        self.status.setText(f"Captured {cap.when}")
        self.show()
        self.raise_()
        self.activateWindow()

    # -- grammar patterns ---------------------------------------------------
    def _update_patterns(self):
        try:
            self.pattern_matches = patterns.detect(self.ja_lines) if self.ja_text.strip() else []
        except Exception:  # noqa: BLE001
            log.exception("Pattern detection failed")
            self.pattern_matches = []
        self._marked_pattern = -1
        self._mark_pattern_tokens(set())
        if not self.pattern_matches:
            self.pattern_bar.hide()
            return
        chips = []
        for i, m in enumerate(self.pattern_matches):
            chips.append(f"<a href='p:{i}' style='text-decoration:none'><b>{html.escape(m.pattern.form)}</b></a> "
                         f"<span style='color:gray'>{html.escape(m.pattern.meaning)} · {m.pattern.jlpt}</span>")
        self.pattern_bar.setText("📘 " + "&nbsp;&nbsp;│&nbsp;&nbsp;".join(chips))
        self.pattern_bar.setToolTip("Grammar points in this sentence — click one to underline it")
        self.pattern_bar.show()
        log.info("Grammar points: %s", ", ".join(m.pattern.form for m in self.pattern_matches))

    def _pattern_clicked(self, href: str):
        try:
            i = int(href.split(":", 1)[1])
        except ValueError:
            return
        if i == self._marked_pattern or not (0 <= i < len(self.pattern_matches)):
            self._marked_pattern = -1
            self._mark_pattern_tokens(set())
            return
        m = self.pattern_matches[i]
        line = self.ja_lines[m.line]
        self._marked_pattern = i
        self._mark_pattern_tokens({id(t) for t in line[m.first:m.last + 1]})
        self.status.setText(f"{m.pattern.form}: {m.pattern.meaning} ({m.pattern.jlpt})")

    def _mark_pattern_tokens(self, ids: set[int]):
        for key, sec in self.sections.items():
            if key in RENDER_MODE and hasattr(sec.view, "mark_tokens"):
                sec.view.mark_tokens(ids)

    def _patterns_html(self, tok) -> str:
        ms = patterns.matches_for(self.pattern_matches, self.ja_lines, tok)
        return "".join(f"<div>📘 <b>{html.escape(m.pattern.form)}</b> — {html.escape(m.pattern.meaning)} "
                       f"<span style='color:gray'>({m.pattern.jlpt})</span></div>" for m in ms)

    # -- shadowing ----------------------------------------------------------
    def open_shadow(self):
        from . import shadow

        sentence = flatten(self.ja_text, "ja")
        if not sentence:
            return
        self.speaker.stop()
        try:
            dlg = shadow.open_dialog(sentence, self.cfg.voice, self._speed_value(), self)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        except Exception:  # noqa: BLE001
            log.exception("Shadowing window failed")

    # -- tutor --------------------------------------------------------------
    def open_ask(self):
        from .ask import AskDialog

        sentence = flatten(self.ja_text, "ja")
        if not sentence:
            return
        english = self.sections["english"].view.toPlainText()
        if english.startswith(("Translating", "(Translation failed")):
            english = ""
        dlg = AskDialog(self.dictionary.kanji, sentence, english,
                        [f"{m.pattern.form} ({m.pattern.meaning})" for m in self.pattern_matches], self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def _play_word(self):
        c = self._lookup_ctx
        if not c or not self.popup.isVisible():
            return
        word = c["tok"].surface
        log.info("Read word: %s", word)
        self.speaker.play(word, self._speed_value())

    def _play_part(self, tok, how: str):
        """Right-click playback: the sentence from a word on, or just the word's phrase."""
        flat = [x for ln in self.ja_lines for x in ln]
        for line in self.ja_lines:
            for i, t in enumerate(line):
                if t is tok:
                    if how == "from":
                        k = next(n for n, x in enumerate(flat) if x is tok)
                        text = "".join(x.surface for x in flat[k:])
                    else:   # the word plus the particles/endings attached to it
                        j = i + 1
                        while j < len(line) and line[j].pos in ("助詞", "助動詞", "接尾辞"):
                            j += 1
                        text = "".join(x.surface for x in line[i:j])
                    log.info("Play %s: %s", how, short(text))
                    self.speaker.play(text, self._speed_value())
                    return

    def _play_selection(self):
        text = self._sel_result if (self._sel_view is self.sections["english"].view) else self._sel_text
        if text:
            log.info("Read selection: %s", short(text))
            self.speaker.play(text, self._speed_value())

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
        if t == QEvent.Type.KeyPress and ev.key() == lookupkey.key() and not ev.isAutoRepeat() \
                and self.isVisible():
            v = self._view_under_cursor()
            if v is not None:
                v.clear_hover()
                v.lookup_at(v.viewport().mapFromGlobal(QCursor.pos()))
        if t == QEvent.Type.MouseButtonPress and getattr(self, "_en_dirty", False) and any(
                obj is self.sections[k].view.viewport() for k in RENDER_MODE):
            self._apply_english_edit()
        if t == QEvent.Type.MouseButtonPress and self.popup.isVisible() \
                and any(obj is s.view.viewport() for s in self.sections.values()):
            self._hide_popup()
        return False

    def hideEvent(self, e):
        self._hide_popup()
        self.speaker.stop()
        super().hideEvent(e)
