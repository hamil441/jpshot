"""A text view that draws furigana above kanji (Qt's rich text has no <ruby> support).

It behaves like the other rows: words wrap, can be selected (drag) and copied (Ctrl+C or the
Copy button), Shift-hover (or plain hover in grammar mode) looks words up, and grammar mode
colors words by part of speech.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

from . import grammar, japanese, lookupkey, pitch
from .japanese import Token

log = logging.getLogger("jpshot.furigana")
PAD = 6
TOP = 0


@dataclass
class _Seg:
    base: str
    ruby: str
    x: int       # offset inside the item
    w: int


@dataclass
class _Item:
    tok: Token
    x: int
    y: int       # top of the line
    w: int
    segs: list


class _Canvas(QWidget):
    def __init__(self, view: "FuriganaView"):
        super().__init__()
        self.view = view
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.lines: list[list[Token]] | None = None
        self.message = ""
        self.items: list[_Item] = []
        self.line_h = 0
        self.base_font = QFont()
        self.ruby_font = QFont()
        self.hover: _Item | None = None
        self.sel: tuple[int, int] | None = None   # inclusive item index range
        self._anchor: int | None = None
        self._dragged = False
        self.colored = False
        self.hover_lookup = False
        self.color_fn = grammar.color_for
        self.pitch_fn = None   # tok -> [high?, …] per sound, in pitch mode

    # -- layout -----------------------------------------------------------
    def set_fonts(self, base: QFont):
        self.base_font = QFont(base)
        self.ruby_font = QFont(base)
        self.ruby_font.setPointSize(max(7, round(base.pointSize() * 0.5)))
        self.relayout()

    def relayout(self):
        fb, fr = QFontMetrics(self.base_font), QFontMetrics(self.ruby_font)
        self.line_h = TOP + fr.height() + fb.height() + 6
        self.items = []
        width = max(50, self.width())
        x = y = PAD
        if self.lines is None:
            text_h = fb.boundingRect(QRect(0, 0, width - 2 * PAD, 10000),
                                     Qt.TextFlag.TextWordWrap, self.message).height()
            self.setMinimumHeight(text_h + 2 * PAD)
            self.update()
            return
        for li, line in enumerate(self.lines):
            if li:
                x = PAD
                y += self.line_h
            for tok in line:
                if tok.space_before:
                    x += fb.horizontalAdvance(tok.space_before)
                segs = []
                sx = 0
                for base, ruby in self._split(tok):
                    w = max(fb.horizontalAdvance(base), fr.horizontalAdvance(ruby) if ruby else 0)
                    segs.append(_Seg(base, ruby, sx, w))
                    sx += w
                if x + sx > width - PAD and x > PAD:
                    x = PAD
                    y += self.line_h
                self.items.append(_Item(tok, x, y, sx, segs))
                x += sx
        self.setMinimumHeight(y + self.line_h + PAD)
        self.update()

    @staticmethod
    def _split(tok: Token) -> list[tuple[str, str]]:
        if not tok.reading or not japanese.has_kanji(tok.surface):
            return [(tok.surface, "")]
        prefix, core, rcore, suffix = japanese.furigana_parts(tok.surface, tok.reading)
        if not rcore:
            return [(tok.surface, "")]
        return [(t, r) for t, r in ((prefix, ""), (core, rcore), (suffix, "")) if t]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            self.relayout()

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        pal = self.palette()
        text_col = pal.color(QPalette.ColorRole.Text)
        if self.lines is None:
            p.setFont(self.base_font)
            p.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect().adjusted(PAD, PAD, -PAD, -PAD), Qt.TextFlag.TextWordWrap, self.message)
            return
        fb, fr = QFontMetrics(self.base_font), QFontMetrics(self.ruby_font)
        ruby_h = fr.height()
        sel = self.sel
        hl = QColor(pal.color(QPalette.ColorRole.Highlight))
        hl.setAlpha(110)
        hover_bg = QColor(232, 85, 109, 80)
        for i, it in enumerate(self.items):
            box = QRect(it.x, it.y, it.w, self.line_h)
            if sel and sel[0] <= i <= sel[1]:
                p.fillRect(box, hl)
            if it is self.hover:
                p.fillRect(QRect(it.x, it.y + TOP + ruby_h + 2, it.w, fb.height() + 2), hover_bg)
            col = QColor(text_col)
            if self.colored:
                c = self.color_fn(it.tok)
                if c and isinstance(c, str):
                    col = QColor(c)
            highs = self.pitch_fn(it.tok) if (self.colored and self.pitch_fn) else None
            if highs:
                self._paint_pitch(p, it, highs, text_col, fb, fr)
                continue
            ruby_col = QColor(col)
            ruby_col.setAlpha(190)
            for s in it.segs:
                if s.ruby:
                    p.setFont(self.ruby_font)
                    p.setPen(ruby_col)
                    rw = fr.horizontalAdvance(s.ruby)
                    p.drawText(it.x + s.x + (s.w - rw) // 2, it.y + TOP + fr.ascent(), s.ruby)
                p.setFont(self.base_font)
                p.setPen(col)
                bw = fb.horizontalAdvance(s.base)
                p.drawText(it.x + s.x + (s.w - bw) // 2, it.y + TOP + ruby_h + 2 + fb.ascent(), s.base)

    def _paint_pitch(self, p, it, highs, text_col, fb, fr):
        """Color each sound of the reading high (orange) or low (blue)."""
        ruby_h = fr.height()
        idx = 0
        cells: list[tuple[int, int, bool]] = []   # (x0, x1, high) for every sound, left to right
        for s in it.segs:
            kana = s.ruby or s.base
            ms = pitch.morae(kana)
            hs = (highs[idx:idx + len(ms)] + [False] * len(ms))[:len(ms)]
            idx += len(ms)
            if s.ruby:   # kanji with reading: base in normal color, reading colored per sound
                p.setFont(self.base_font)
                p.setPen(text_col)
                bw = fb.horizontalAdvance(s.base)
                p.drawText(it.x + s.x + (s.w - bw) // 2, it.y + TOP + ruby_h + 2 + fb.ascent(), s.base)
                metrics, font, base_y = fr, self.ruby_font, it.y + TOP + fr.ascent()
            else:        # kana: the characters themselves carry the pitch
                metrics, font, base_y = fb, self.base_font, it.y + TOP + ruby_h + 2 + fb.ascent()
            x = it.x + s.x + (s.w - metrics.horizontalAdvance(kana)) // 2
            p.setFont(font)
            for m, h in zip(ms, hs):
                w = metrics.horizontalAdvance(m)
                p.setPen(QColor(pitch.HIGH if h else pitch.LOW))
                p.drawText(x, base_y, m)
                cells.append((x, x + w, h))
                x += w

    # -- hit testing / mouse ----------------------------------------------
    def index_at(self, pos: QPoint) -> int | None:
        for i, it in enumerate(self.items):
            if it.x <= pos.x() < it.x + it.w and it.y <= pos.y() < it.y + self.line_h:
                return i
        return None

    def lookup_at(self, pos: QPoint):
        i = self.index_at(pos)
        if i is None:
            return
        it = self.items[i]
        if not it.tok.lookupable or it is self.hover:
            return
        self.hover = it
        self.update()
        r = QRect(it.x, it.y, it.w, self.line_h)
        glob = QRect(self.mapToGlobal(r.topLeft()), r.size())
        self.view.lookup_requested.emit(it.tok, glob)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._anchor = self.index_at(e.position().toPoint())
            self._dragged = False
            had = self.sel is not None
            self.sel = None
            self.update()
            if had:
                self.view.selectionChanged.emit()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if e.buttons() & Qt.MouseButton.LeftButton and self._anchor is not None:
            i = self.index_at(pos)
            if i is not None:
                self._dragged = True
                self.sel = (min(self._anchor, i), max(self._anchor, i))
                self.update()
            return
        if e.modifiers() & lookupkey.modifier():
            self.lookup_at(pos)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._dragged:
            self.view.selectionChanged.emit()
        self._anchor = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        i = self.index_at(e.position().toPoint())
        if i is not None:
            self.sel = (i, i)
            self.update()
            self.view.selectionChanged.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_C and e.modifiers() & Qt.KeyboardModifier.ControlModifier \
                and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            text = self.view.original_of_selection()
            if text:
                from .ui_result import copy_text
                copy_text(text)
            return
        if e.key() == Qt.Key.Key_A and e.modifiers() & Qt.KeyboardModifier.ControlModifier and self.items:
            self.sel = (0, len(self.items) - 1)
            self.update()
            self.view.selectionChanged.emit()
            return
        super().keyPressEvent(e)


class FuriganaView(QScrollArea):
    """Drop-in for WordView in the Furigana row."""

    lookup_requested = Signal(object, QRect)
    selectionChanged = Signal()

    def __init__(self, font: QFont):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(44)
        self.canvas = _Canvas(self)
        self.canvas.setAutoFillBackground(True)
        self.canvas.setBackgroundRole(QPalette.ColorRole.Base)
        self.setWidget(self.canvas)
        self.canvas.set_fonts(font)

    # WordView-compatible API ---------------------------------------------------
    def viewport(self):  # noqa: D401 - callers map coordinates against the canvas
        return self.canvas

    @property
    def spans(self):
        return self.canvas.items

    @property
    def hover_lookup(self):
        return self.canvas.hover_lookup

    @hover_lookup.setter
    def hover_lookup(self, on: bool):
        self.canvas.hover_lookup = on

    def setFont(self, f: QFont):
        super().setFont(f)
        self.canvas.set_fonts(f)

    def set_content(self, text: str, spans=None):
        """Show a plain message (e.g. 'translating…')."""
        c = self.canvas
        c.lines, c.message, c.hover, c.sel = None, text, None, None
        c.relayout()

    def set_lines(self, lines: list[list[Token]]):
        c = self.canvas
        c.lines, c.message, c.hover, c.sel = lines, "", None, None
        c.relayout()

    @property
    def color_fn(self):
        return self.canvas.color_fn

    @color_fn.setter
    def color_fn(self, fn):
        self.canvas.color_fn = fn

    @property
    def pitch_fn(self):
        return self.canvas.pitch_fn

    @pitch_fn.setter
    def pitch_fn(self, fn):
        self.canvas.pitch_fn = fn

    def refresh_colors(self):
        self.canvas.update()

    def set_colors(self, on: bool):
        self.canvas.colored = on
        self.canvas.update()

    def clear_hover(self):
        self.canvas.hover = None
        self.canvas.update()

    def lookup_at(self, pos: QPoint):
        self.canvas.lookup_at(pos)

    def toPlainText(self) -> str:  # noqa: N802 (Qt naming)
        c = self.canvas
        if c.lines is None:
            return c.message
        return japanese.render(c.lines, "furigana")[0]

    def original_of_selection(self) -> str:
        c = self.canvas
        if not c.sel:
            return ""
        out = []
        for i in range(c.sel[0], c.sel[1] + 1):
            t = c.items[i].tok
            if out and t.space_before:
                out.append(t.space_before)
            out.append(t.surface)
        return "".join(out)
