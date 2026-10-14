"""Pitch accent from UniDic's accent type (aType): pattern, colors and a drawn contour.

Patterns (Tokyo standard):
  heiban (平板)     0   low first mora, then high; stays high into a following particle
  atamadaka (頭高)  1   high first mora, then low
  nakadaka (中高)   k   low, high up to mora k, then low (1 < k < length)
  odaka (尾高)      n   low, high to the end, drops on a following particle (k = length)
Colors follow the common learner convention (blue / red / orange / green).
"""
from __future__ import annotations

import html
import re

from .japanese import Token, display, kata_to_hira

SMALL = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")
COLORS = {"heiban": "#3b8fe8", "atamadaka": "#e8556d", "nakadaka": "#f0a030", "odaka": "#2fb383"}
HIGH, LOW = "#ff8a3d", "#5aa9ff"       # per-sound colors in the kana rows
MUTED = "#8e9099"
TERMS = {   # term, reading, literal meaning, what it sounds like
    "heiban": ("平板", "へいばん", "flat", "low first sound, then high and stays high (even on a following particle)"),
    "atamadaka": ("頭高", "あたまだか", "head-high", "high first sound, then low"),
    "nakadaka": ("中高", "なかだか", "middle-high", "low, rises, then drops inside the word"),
    "odaka": ("尾高", "おだか", "tail-high", "low, rises to the end, drops on the following particle"),
}
NAMES = {
    "heiban": "heiban (flat) — rises after the first sound and stays high",
    "atamadaka": "atamadaka — high on the first sound, then drops",
    "nakadaka": "nakadaka — rises, then drops inside the word",
    "odaka": "odaka — rises and drops right after the word",
}
NO_ACCENT_POS = {"助詞", "助動詞", "補助記号", "記号", "空白", "接尾辞"}


def morae(kana: str) -> list[str]:
    out: list[str] = []
    for c in kana:
        if c in SMALL and out:
            out[-1] += c
        else:
            out.append(c)
    return out


def accent_of(tok: Token) -> int | None:
    m = re.match(r"\d+", tok.atype or "")
    return int(m.group()) if m else None


def _reading(tok: Token) -> str:
    """Reading the accent refers to: dictionary form for verbs/adjectives, else as written."""
    if tok.pos in ("動詞", "形容詞") and tok.kana_base:
        return kata_to_hira(tok.kana_base)
    return tok.reading or kata_to_hira(tok.surface)


def kind(tok: Token) -> str | None:
    if not tok.lookupable or tok.pos in NO_ACCENT_POS:
        return None
    n = accent_of(tok)
    if n is None:
        return None
    count = len(morae(_reading(tok)))
    if n == 0:
        return "heiban"
    if n == 1:
        return "atamadaka"
    return "odaka" if n >= count else "nakadaka"


def color_for(tok: Token) -> str | None:
    k = kind(tok)
    return COLORS.get(k) if k else None


def pattern_html(tok: Token) -> str:
    """Reading with high morae overlined and ꜜ where the pitch drops."""
    k = kind(tok)
    if not k:
        return ""
    reading = _reading(tok)
    ms = morae(reading)
    n = accent_of(tok) or 0
    if n == 0:
        highs = [False] + [True] * (len(ms) - 1)
    else:
        highs = [i == 0 if n == 1 else (0 < i < n) for i in range(len(ms))]
    parts = []
    for i, (m, hi) in enumerate(zip(ms, highs)):
        cell = html.escape(m)
        parts.append(f"<span style='text-decoration:overline'>{cell}</span>" if hi else cell)
        if n and i == n - 1:
            parts.append(f"<span style='color:{COLORS[k]}'>ꜜ</span>")
    word = "" if reading == (tok.reading or "") or tok.pos not in ("動詞", "形容詞") else " (dictionary form)"
    return (f"<div><span style='color:{COLORS[k]}'>■</span> <span style='font-size:13pt'>{''.join(parts)}</span>"
            f"{html.escape(word)} <span style='color:gray;font-size:9pt'>{html.escape(NAMES[k])}</span></div>")


def legend_html(shown: set[str] | None = None) -> str:
    """Pattern colors (日本語/Rōmaji rows) and/or high/low (ひらがな/Furigana rows), for the rows shown."""
    shown = shown if shown is not None else {"japanese", "hiragana"}
    lines = []
    if shown & {"japanese", "romaji"}:
        lines.append("  ".join(
            f"<span style='color:{COLORS[k]}'>■</span> {TERMS[k][0]} ({TERMS[k][1]}) “{TERMS[k][2]}”"
            for k in ("heiban", "atamadaka", "nakadaka", "odaka")))
    if shown & {"furigana", "hiragana"}:
        lines.append(f"<span style='color:{HIGH}'>■</span> high  <span style='color:{LOW}'>■</span> low  "
                     "<span style='color:gray'>— the pitch drops where orange turns blue</span>")
    return "<br>".join(lines)


def legend_tooltip() -> str:
    return "\n".join(f"{TERMS[k][0]} ({TERMS[k][1]}) {k} — “{TERMS[k][2]}”: {TERMS[k][3]}"
                     for k in ("heiban", "atamadaka", "nakadaka", "odaka"))


def word_color(tok: Token) -> str | None:
    """Whole-word color for rows with kanji or rōmaji (particles get a muted color)."""
    c = color_for(tok)
    if c:
        return c
    if tok.pos in ("助詞", "助動詞") or (tok.pos == "接尾辞" and not tok.atype):
        return MUTED
    return None


def word_highs(tok: Token) -> list[bool] | None:
    """High/low for each sound of the word as displayed in kana (None if unknown)."""
    n = accent_of(tok)
    if n is None or not tok.lookupable or tok.pos in NO_ACCENT_POS:
        return None
    ms = morae(display(tok, "hiragana"))
    if not ms:
        return None
    if n == 0:
        return [False] + [True] * (len(ms) - 1)
    return [i == 0 if n == 1 else (0 < i < n) for i in range(len(ms))]


def sentence_highs(lines: list[list[Token]]) -> dict[int, list[bool]]:
    """Per-sound pitch for every token (keyed by id(token)); particles/endings follow the word before:
    high after a heiban word, low after a word that already dropped."""
    out: dict[int, list[bool]] = {}
    for line in lines:
        state: bool | None = None          # pitch level carried into following particles
        for tok in line:
            highs = word_highs(tok)
            if highs is not None:
                out[id(tok)] = highs
                state = accent_of(tok) == 0
                if len(highs) == 1 and accent_of(tok) == 0:
                    state = True           # one-sound heiban word: rises on the particle
                continue
            if tok.pos in ("助詞", "助動詞", "接尾辞") and state is not None:
                ms = morae(display(tok, "hiragana"))
                out[id(tok)] = [state] * len(ms)
                continue
            state = None
    return out


def mora_colors(highs: list[bool] | None) -> list[str] | None:
    return [HIGH if h else LOW for h in highs] if highs else None
