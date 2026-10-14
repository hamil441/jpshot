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
    pron: str = ""    # pronunciation in hiragana (は read as わ etc.)
    pos2: str = ""
    ctype: str = ""   # conjugation type, e.g. 五段-カ行
    cform: str = ""   # conjugation form, e.g. 連用形-一般

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
                pron=kata_to_hira(_feat(w, "pron") or ""),
                pos2=_feat(w, "pos2") or "",
                ctype=_feat(w, "cType") or "",
                cform=_feat(w, "cForm") or "",
            ))
        lines.append(toks)
        log.debug("tokens: %s", " | ".join(f"{t.surface}/{t.reading or '-'}/{t.base}/{t.pos}" for t in toks))
    return lines


def furigana_parts(surface: str, reading: str) -> tuple[str, str, str, str]:
    """Split into (kana prefix, kanji core, reading of the core, kana suffix).

    食べ + たべ -> ("", "食", "た", "べ"); お茶 + おちゃ -> ("お", "茶", "ちゃ", "")
    """
    s, r = surface, reading
    suffix = prefix = ""
    while len(s) > 1 and r and _is_kana(s[-1]) and kata_to_hira(s[-1]) == r[-1]:
        suffix = s[-1] + suffix
        s, r = s[:-1], r[:-1]
    while len(s) > 1 and r and _is_kana(s[0]) and kata_to_hira(s[0]) == r[0]:
        prefix += s[0]
        s, r = s[1:], r[1:]
    return prefix, s, r, suffix


def furigana(surface: str, reading: str) -> str:
    """Inline form used for copying: 食べ + たべ -> 食(た)べ"""
    prefix, core, rcore, suffix = furigana_parts(surface, reading)
    if not rcore:
        return surface
    return f"{prefix}{core}({rcore}){suffix}"


_KANA_ROMAJI = (
    "あa いi うu えe おo かka きki くku けke こko さsa しshi すsu せse そso たta ちchi つtsu てte とto "
    "なna にni ぬnu ねne のno はha ひhi ふfu へhe ほho まma みmi むmu めme もmo やya ゆyu よyo "
    "らra りri るru れre ろro わwa をo んn がga ぎgi ぐgu げge ごgo ざza じji ずzu ぜze ぞzo "
    "だda ぢji づzu でde どdo ばba びbi ぶbu べbe ぼbo ぱpa ぴpi ぷpu ぺpe ぽpo "
    "ぁa ぃi ぅu ぇe ぉo ゃya ゅyu ょyo ゎwa ゐi ゑe ゔvu"
)
MONO = {item[0]: item[1:] for item in _KANA_ROMAJI.split()}
DIGRAPHS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo", "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo", "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "しぇ": "she", "じぇ": "je", "ちぇ": "che", "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo", "つぁ": "tsa", "いぇ": "ye",
}
PUNCT_ROMAJI = {"。": ".", "、": ",", "「": '"', "」": '"', "『": '"', "』": '"', "！": "!", "？": "?",
                "・": " ", "（": "(", "）": ")", "：": ":", "；": ";", "…": "...", "〜": "~", "\u3000": " ",
                "，": ",", "．": "."}
PARTICLE_ROMAJI = {"は": "wa", "へ": "e", "を": "o"}


def to_romaji(text: str) -> str:
    """Hepburn romanization of kana (katakana is converted first). Other characters pass through."""
    s = kata_to_hira(text)
    out: list[str] = []
    sokuon = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "っ":
            sokuon = True
            i += 1
            continue
        if s[i:i + 2] in DIGRAPHS:
            r = DIGRAPHS[s[i:i + 2]]
            i += 2
        elif c in MONO:
            r = MONO[c]
            i += 1
        elif c == "ー":  # long vowel mark: repeat the previous vowel
            r = out[-1][-1] if out and out[-1] and out[-1][-1] in "aeiou" else ""
            i += 1
        else:
            r = PUNCT_ROMAJI.get(c, c)
            i += 1
        if sokuon and r and r[0].isalpha() and r[0] not in "aeiou":
            r = ("t" if r.startswith("ch") else r[0]) + r
        sokuon = False
        if out and out[-1] == "n" and r and r[0] in "aeiouy":  # ん before a vowel: n'
            out[-1] = "n'"
        out.append(r)
    return "".join(out)


def romaji_of(tok: Token) -> str:
    if tok.pos == "助詞" and tok.surface in PARTICLE_ROMAJI:
        return PARTICLE_ROMAJI[tok.surface]
    if tok.reading:
        r = tok.reading
        # こんにちは / こんばんは: final は is pronounced わ
        if r[-1:] in ("は", "へ") and tok.pron[-1:] in ("わ", "え") and len(r) > 1:
            r = r[:-1] + tok.pron[-1]
        return to_romaji(r)
    if has_kanji(tok.surface):
        return tok.surface  # unknown reading: leave as is
    return to_romaji(tok.surface)


_OPENERS = set("「『（(\"")
_ATTACH_POS = {"助動詞", "接尾辞"}
_ATTACH_PARTICLES = {"て", "で", "ば"}


def _romaji_space(prev: Token | None, tok: Token) -> bool:
    """Should a space separate these two tokens when written in romaji?"""
    if prev is None or tok.space_before:
        return False
    if prev.surface in _OPENERS:
        return False
    if tok.pos in NON_WORD_POS:
        return tok.surface in _OPENERS
    if tok.pos in _ATTACH_POS:
        return False
    if tok.pos == "助詞" and tok.surface in _ATTACH_PARTICLES:
        return False
    return True


def display(tok: Token, mode: str) -> str:
    if mode == "romaji":
        return romaji_of(tok)
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
        prev = None
        for t in line:
            if mode == "romaji" and _romaji_space(prev, t):
                parts.append(" ")
                pos += 1
            prev = t
            if t.space_before:
                parts.append(t.space_before)
                pos += u16len(t.space_before)
            d = display(t, mode)
            spans.append(Span(pos, pos + u16len(d), t))
            parts.append(d)
            pos += u16len(d)
    return "".join(parts), spans


def anki_furigana(lines: list[list[Token]]) -> str:
    """Anki's furigana syntax: 食[た]べる 日本語[にほんご] (a space starts each reading base)."""
    out_lines = []
    for line in lines:
        out = ""
        for t in line:
            out += t.space_before
            if t.reading and has_kanji(t.surface):
                prefix, core, rcore, suffix = furigana_parts(t.surface, t.reading)
                if rcore:
                    out += prefix
                    if out and not out.endswith(" "):
                        out += " "  # Anki: the reading applies to the text after the last space
                    out += f"{core}[{rcore}]{suffix}"
                    continue
            out += t.surface
        out_lines.append(out)
    return "\n".join(out_lines)


def span_at(spans: list[Span], index: int) -> Span | None:
    i = bisect.bisect_right([s.start for s in spans], index) - 1
    if 0 <= i < len(spans) and spans[i].start <= index < spans[i].end:
        return spans[i]
    return None
