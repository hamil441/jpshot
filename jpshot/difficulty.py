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

CONTENT_POS = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞"}
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
    if not info:
        return 5.0
    jlpt, grade = info.get("jlpt"), info.get("grade")
    if jlpt:
        return max(1.0, min(5.0, 6 - int(jlpt)))
    if grade:
        g = int(grade)
        return 1 + 0.5 * g if g <= 6 else (4.5 if g == 8 else 5.0)
    return 5.0


def estimate(lines: list[list[Token]], kanji_info, word_entries, max_words: int = 12) -> Difficulty | None:
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
    word_scores, rare = [], []
    for w in words:
        try:
            entries = word_entries(w)
        except Exception:  # noqa: BLE001
            entries = []
        e = entries[0] if entries else None
        if e is None:
            h = 4.0
        elif getattr(e, "jlpt", None):
            h = float(6 - e.jlpt)
        elif getattr(e, "common", None):
            h = 2.5
        else:
            h = 4.5
        word_scores.append(h)
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
    level = max(1, min(5, round(score)))
    d = Difficulty(level=level, jlpt=f"N{6 - level}", label=LABELS[level], score=round(score, 2), reasons=reasons)
    log.info("Difficulty %s (%.2f): vocab %.1f, kanji %.1f, grammar %.1f, length %.1f — %s",
             d.jlpt, score, v_score, k_score, g_score, l_score, "; ".join(reasons))
    return d
