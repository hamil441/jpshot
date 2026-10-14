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

from .japanese import Token, kata_to_hira

SMALL = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")
COLORS = {"heiban": "#3b8fe8", "atamadaka": "#e8556d", "nakadaka": "#f0a030", "odaka": "#2fb383"}
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


def legend_html() -> str:
    return "  ".join(f"<span style='color:{COLORS[k]}'>■</span> {k}" for k in ("heiban", "atamadaka", "nakadaka", "odaka"))
