"""Japanese word segmentation (MeCab/UniDic via fugashi), readings, furigana and hiragana rendering."""
from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass

from .ocr import JA_RE

log = logging.getLogger("jpshot.ja")

NON_WORD_POS = {"補助記号", "空白", "記号"}

# UniDic picks formal readings for a few very common words; use the everyday ones.
READING_FIXES = {"日本": "にほん", "日本人": "にほんじん"}

_tagger = None


def get_tagger():
    global _tagger
    if _tagger is None:
        import fugashi

        from .log import timed
        with timed(log, "loading MeCab/UniDic"):
            _tagger = fugashi.Tagger()  # uses unidic-lite
        log.info("Japanese tokenizer ready (%s)", getattr(_tagger, "dictionary_info", [{}])[0].get("filename", "unidic"))
    return _tagger


@dataclass
class Token:
    surface: str
    reading: str      # hiragana reading ("" if not Japanese)
    base: str         # dictionary form (e.g. 食べ -> 食べる)
    lemma: str
    pos: str
    lookupable: bool
    space_before: str = ""

    def candidates(self) -> list[str]:
        out = []
        for c in (self.base, self.lemma, self.surface):
            if c and c not in out:
                out.append(c)
        return out


@dataclass
class Span:
    start: int  # UTF-16 offsets, to match QTextDocument positions
    end: int
    token: Token


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def has_kanji(s: str) -> bool:
    return any("\u3400" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff"
               or "\U00020000" <= c <= "\U0003134f" or c in "々〆" for c in s)


def _is_kana(c: str) -> bool:
    return "぀" <= c <= "ヿ"


def _feat(word, name: str):
    v = getattr(word.feature, name, None)
    return None if v in (None, "*", "") else v


def tokenize(text: str) -> list[list[Token]]:
    tagger = get_tagger()
    lines = []
    for line in text.split("\n"):
        toks = []
        for w in tagger(line):
            surface = w.surface
            kana = _feat(w, "kana")
            reading = kata_to_hira(kana) if kana and JA_RE.search(surface) else ""
            reading = READING_FIXES.get(surface, reading)
            pos = _feat(w, "pos1") or ""
            base = _feat(w, "orthBase") or surface
            lemma = (_feat(w, "lemma") or "").split("-")[0]
            toks.append(Token(
                surface=surface, reading=reading, base=base, lemma=lemma, pos=pos,
                lookupable=pos not in NON_WORD_POS and bool(JA_RE.search(surface)),
                space_before=getattr(w, "white_space", "") or "",
            ))
        lines.append(toks)
        log.debug("tokens: %s", " | ".join(f"{t.surface}/{t.reading or '-'}/{t.base}/{t.pos}" for t in toks))
    return lines


def furigana(surface: str, reading: str) -> str:
    """食べ + たべ -> 食(た)べ ; 日本語 + にほんご -> 日本語(にほんご)"""
    s, r = surface, reading
    suffix = prefix = ""
    while len(s) > 1 and r and _is_kana(s[-1]) and kata_to_hira(s[-1]) == r[-1]:
        suffix = s[-1] + suffix
        s, r = s[:-1], r[:-1]
    while len(s) > 1 and r and _is_kana(s[0]) and kata_to_hira(s[0]) == r[0]:
        prefix += s[0]
        s, r = s[1:], r[1:]
    if not r:
        return surface
    return f"{prefix}{s}({r}){suffix}"


def display(tok: Token, mode: str) -> str:
    if mode == "original" or not tok.reading or not has_kanji(tok.surface):
        return tok.surface
    if mode == "hiragana":
        return tok.reading
    return furigana(tok.surface, tok.reading)


def u16len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def render(lines: list[list[Token]], mode: str) -> tuple[str, list[Span]]:
    parts: list[str] = []
    spans: list[Span] = []
    pos = 0
    for i, line in enumerate(lines):
        if i:
            parts.append("\n")
            pos += 1
        for t in line:
            if t.space_before:
                parts.append(t.space_before)
                pos += u16len(t.space_before)
            d = display(t, mode)
            spans.append(Span(pos, pos + u16len(d), t))
            parts.append(d)
            pos += u16len(d)
    return "".join(parts), spans


def span_at(spans: list[Span], index: int) -> Span | None:
    i = bisect.bisect_right([s.start for s in spans], index) - 1
    if 0 <= i < len(spans) and spans[i].start <= index < spans[i].end:
        return spans[i]
    return None
