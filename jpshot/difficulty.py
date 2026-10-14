"""Estimate how hard a Japanese sentence is for a learner, on a JLPT-like scale (N5 easy … N1 hard).

Combines: how advanced its kanji are (JLPT level / school grade), how common its words are
(dictionary JLPT tags and 'common word' markers), grammar load (auxiliaries, clause joins, keigo)
and length. Everything is a rough estimate meant for sorting and tagging cards.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .japanese import Token
from .kanji import is_kanji

log = logging.getLogger("jpshot.difficulty")

CONTENT_POS = {"接尾辞", "名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞"}
KEIGO = {"いらっしゃる", "おっしゃる", "申す", "参る", "致す", "存じる", "為さる", "下さる", "伺う", "召し上がる",
         "御座る", "頂く", "差し上げる"}
LABELS = {1: "Beginner", 2: "Elementary", 3: "Intermediate", 4: "Upper-intermediate", 5: "Advanced"}
COLORS = {1: "#2fb383", 2: "#7cc04b", 3: "#f0a030", 4: "#e8743d", 5: "#e8556d"}


@dataclass
class Difficulty:
    level: int                 # 1 (easy) … 5 (hard)
    jlpt: str                  # "N5" … "N1"
    label: str
    score: float
    reasons: list[str] = field(default_factory=list)
    word_hardness: dict = field(default_factory=dict)    # dictionary form -> 1.0 … 5.0
    kanji_hardness: dict = field(default_factory=dict)   # kanji -> 1.0 … 5.0

    @property
    def color(self) -> str:
        return COLORS[self.level]

    @property
    def stars(self) -> str:
        return "★" * self.level + "☆" * (5 - self.level)

    def summary(self) -> str:
        return f"{self.jlpt} · {self.label}"


def _blend(values: list[float]) -> float:
    if not values:
        return 1.0
    return 0.6 * (sum(values) / len(values)) + 0.4 * max(values)


def _kanji_hardness(info: dict | None) -> float:
    """1 (very basic) … 5 (rare). School grade and newspaper frequency are the reliable signals;
    the kanji 'jlpt' field from KANJIDIC/kanjiapi is the OLD 4-level test (4 = easiest)."""
    if not info:
        return 3.5   # unknown (lookup failed): don't pretend it's rare
    scores = []
    grade = info.get("grade")
    if grade:
        g = int(grade)
        scores.append({1: 1.0, 2: 1.0, 3: 1.5, 4: 2.0, 5: 2.5, 6: 2.5}.get(g, 3.5 if g == 8 else 5.0))
    freq = info.get("freq_mainichi_shinbun") or info.get("freq")
    if freq:
        f = int(freq)
        scores.append(1.0 if f <= 300 else 1.5 if f <= 600 else 2.0 if f <= 1000 else 2.5 if f <= 1500
                      else 3.0 if f <= 2000 else 4.0)
    if not scores and info.get("jlpt"):
        scores.append({4: 1.0, 3: 2.0, 2: 3.0, 1: 4.5}.get(int(info["jlpt"]), 3.5))
    return min(scores) if scores else 5.0


def entry_hardness(e) -> float:
    """1 (very basic) … 5 (rare) for one dictionary entry."""
    if getattr(e, "jlpt", None):
        return float(6 - e.jlpt)
    rank = getattr(e, "rank", None)
    if rank:
        return 1.0 if rank <= 4 else 1.5 if rank <= 8 else 2.0 if rank <= 16 else 2.5 if rank <= 30 else 3.0
    if getattr(e, "common", None):
        return 2.2   # marked common (ichi1/news1/spec): everyday vocabulary
    return 4.5


def word_hardness(word: str, entries) -> tuple[float, bool]:
    """(hardness, found). Uses the EASIEST entry that is really this word (spelling or reading matches),
    so a rare homonym (個々 for ここ) can't make an everyday word look hard."""
    matching = [e for e in entries if word in (getattr(e, "forms", None) or [e.word, e.reading])]
    if not matching:
        matching = [e for e in entries if e.word == word or e.reading == word]
    if matching:
        return min(entry_hardness(e) for e in matching), True
    return (3.0 if not any(is_kanji(c) for c in word) else 4.0), False


def _level(h: float) -> int:
    return max(1, min(5, int(h + 0.5)))


def estimate(lines: list[list[Token]], kanji_info, word_entries, max_words: int = 30) -> Difficulty | None:
    """kanji_info(ch) -> dict | None (kanjiapi-like); word_entries(word) -> list[Entry]."""
    tokens = [t for line in lines for t in line]
    text = "".join(t.surface for t in tokens)
    if not text.strip():
        return None
    reasons: list[str] = []

    # kanji
    kanji_scores = {}
    for ch in dict.fromkeys(c for c in text if is_kanji(c) and c not in "々〆"):
        kanji_scores[ch] = _kanji_hardness(kanji_info(ch))
    k_score = _blend(list(kanji_scores.values()))
    hard_kanji = [c for c, h in sorted(kanji_scores.items(), key=lambda x: -x[1]) if h >= 4][:4]
    if hard_kanji:
        reasons.append("advanced kanji: " + "、".join(hard_kanji))
    elif kanji_scores:
        reasons.append(f"{len(kanji_scores)} kanji, all fairly basic")
    else:
        reasons.append("no kanji")

    # vocabulary
    words = list(dict.fromkeys(t.base for t in tokens if t.lookupable and t.pos in CONTENT_POS))[:max_words]
    word_scores, rare, word_h = [], [], {}
    for w in words:
        try:
            entries = word_entries(w) or []
        except Exception:  # noqa: BLE001
            entries = []
        h, found = word_hardness(w, entries)
        # a word is pulled up by a hard kanji, but frequent words much less (everyone knows 友達)
        kh = [kanji_scores.get(c) or _kanji_hardness(kanji_info(c)) for c in w if is_kanji(c) and c not in "々〆"]
        if kh:
            h = max(h, max(kh) - (1.0 if found and h <= 2.5 else 0.0))
        word_h[w] = h
        word_scores.append(h)
        log.debug("word %s -> %.1f (%s)", w, h, "dictionary" if found else "not found")
        if h >= 4.5:
            rare.append(w)
    v_score = _blend(word_scores)
    if rare:
        reasons.append("less common words: " + "、".join(rare[:4]))

    # grammar
    aux = {t.lemma for t in tokens if t.pos == "助動詞"}
    joins = sum(1 for t in tokens if t.pos == "助詞" and t.pos2 == "接続助詞")
    keigo = any(t.lemma in KEIGO for t in tokens)
    g_score = min(5.0, 1 + 0.5 * len(aux) + 0.6 * joins + (1.2 if keigo else 0))
    g_bits = []
    if aux:
        g_bits.append(f"{len(aux)} verb ending{'s' if len(aux) > 1 else ''}")
    if joins:
        g_bits.append(f"{joins} linked clause{'s' if joins > 1 else ''}")
    if keigo:
        g_bits.append("keigo (honorific/humble)")
    if g_bits:
        reasons.append("grammar: " + ", ".join(g_bits))

    # length
    n = sum(len(t.surface) for t in tokens if t.pos not in ("補助記号", "空白"))
    l_score = min(5.0, 1 + n / 20)
    reasons.append(f"{n} characters long")

    score = 0.4 * v_score + 0.35 * k_score + 0.15 * g_score + 0.10 * l_score
    level = _level(score)
    d = Difficulty(level=level, jlpt=f"N{6 - level}", label=LABELS[level], score=round(score, 2), reasons=reasons,
                   word_hardness=word_h, kanji_hardness=kanji_scores)
    log.info("Difficulty %s (%.2f): vocab %.1f, kanji %.1f, grammar %.1f, length %.1f — %s",
             d.jlpt, score, v_score, k_score, g_score, l_score, "; ".join(reasons))
    return d


GRADIENT = ["#2fb383", "#7cc04b", "#e3c03a", "#e8743d", "#e8556d"]   # easy … hard
MUTED = "#8e9099"   # particles and verb endings: not rated


def word_color(d: "Difficulty | None", tok: Token) -> str | None:
    """Color for one word in difficulty-coloring mode (None = leave uncolored)."""
    if d is None:
        return None
    if tok.pos in ("助詞", "助動詞") or (tok.pos == "接尾辞" and not any(is_kanji(c) for c in tok.surface)):
        return MUTED
    if not tok.lookupable or (tok.pos not in CONTENT_POS and tok.pos != "接尾辞"):
        return None
    h = d.word_hardness.get(tok.base)
    if h is None:
        kh = [d.kanji_hardness.get(c, 5.0) for c in tok.surface if is_kanji(c)]
        h = max(kh) if kh else 1.0
    return GRADIENT[_level(h) - 1]


def word_level(d: "Difficulty | None", tok: Token) -> str:
    if d is None:
        return ""
    h = d.word_hardness.get(tok.base)
    if h is None:
        return ""
    return f"N{6 - _level(h)}"


def legend_html() -> str:
    cells = "".join(f"<span style='color:{c}'>■</span>" for c in GRADIENT)
    return (f"word difficulty: easy {cells} hard  <span style='color:gray'>(≈N5 … N1)</span>  ·  "
            f"<span style='color:{MUTED}'>■</span> particles/endings (not rated)")
