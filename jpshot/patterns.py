"""Multi-word grammar patterns (〜わけではない, 〜てしまう, 〜として …) with short explanations.

Each pattern is a regex over the written sentence (or a check on a single token). Matches are
mapped back to tokens so the window can highlight them. Overlaps keep the longest match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .japanese import Token


@dataclass
class Pattern:
    id: str
    regex: str
    form: str
    meaning: str
    jlpt: str
    token_check: object = None   # optional (Token) -> bool, used instead of the regex
    boundary: bool = True        # the match must start where a word starts


@dataclass
class Match:
    pattern: Pattern
    line: int
    first: int      # token index (inclusive)
    last: int       # token index (inclusive)
    text: str


END = r"(?=[。、！？!?\s」』]|$)"

PATTERNS = [
    Pattern("wakedewanai", r"わけ(では|じゃ)(ない|なかった|ありません|ねえ)", "〜わけではない",
            "it's not that… / it doesn't mean that…", "N3"),
    Pattern("wakeganai", r"わけ(が|は)ない", "〜わけがない", "there's no way that…", "N3"),
    Pattern("wakeda", r"わけ(だ|です|か|で)", "〜わけだ", "that's why… / so it means… / no wonder", "N3"),
    Pattern("teshimau", r"(て|で)しま[うっいわえお]|ちゃ[うっいわお]|じゃ[うっいわお]", "〜てしまう / 〜ちゃう",
            "do completely, or do by accident / with regret", "N4"),
    Pattern("nakereba", r"なければ(なら|いけ)|なきゃ|なくては(なら|いけ)|なくちゃ|ないと(いけ|だめ|ダメ)",
            "〜なければならない", "must / have to", "N4"),
    Pattern("temoii", r"(て|で)も(いい|良い|かまわ|構わ)", "〜てもいい", "it's okay to… / may…", "N5"),
    Pattern("tewaikenai", r"(て|で)は(いけ|だめ|ダメ|なら)|ちゃ(いけ|だめ|ダメ)", "〜てはいけない",
            "must not…", "N5"),
    Pattern("takotogaaru", r"(た|だ)ことが(ある|あり|ない|なかっ)", "〜たことがある", "have (ever) done…", "N4"),
    Pattern("kotogadekiru", r"ことが(でき|出来)", "〜ことができる", "can / be able to…", "N4"),
    Pattern("tsumori", r"つもり", "〜つもり", "intend to / plan to…", "N4"),
    Pattern("hazu", r"はず", "〜はずだ", "should be / is expected to (by logic)", "N3"),
    Pattern("kamoshirenai", r"かもしれ|かも" + END, "〜かもしれない", "might / maybe", "N4"),
    Pattern("darou", r"でしょう|だろう", "〜でしょう / だろう", "probably… / …right?", "N4"),
    Pattern("souda", r"そう(だ|です|な|に)", "〜そうだ", "looks like… (appearance) or I hear that… (hearsay)", "N4"),
    Pattern("rashii", r"らしい", "〜らしい", "apparently / seems; or typical of", "N3"),
    Pattern("mitai", r"みたい", "〜みたい", "seems like / like (casual)", "N4"),
    Pattern("youni", r"ように(する|し|なる|なっ)", "〜ようにする / ようになる",
            "make sure to… / come to (be able to)…", "N4"),
    Pattern("youda", r"よう(だ|です|な|に)", "〜ようだ / ような / ように", "seems / like… / so that…", "N4"),
    Pattern("kotoni", r"ことに(する|し|なる|なっ)", "〜ことにする / ことになる",
            "decide to… / it's been decided that…", "N4"),
    Pattern("tameni", r"ために|ため" + END, "〜ために", "in order to… / because of…", "N4"),
    Pattern("nagara", r"ながら", "〜ながら", "while (doing)…", "N4"),
    Pattern("tekara", r"(て|で)から", "〜てから", "after doing…", "N5"),
    Pattern("node", r"ので", "〜ので", "because / so (explaining)", "N4"),
    Pattern("noni", r"のに", "〜のに", "even though / despite (often frustrated)", "N4"),
    Pattern("tara", r"(た|だ)ら(?!い)", "〜たら", "if / when (once…)", "N4"),
    Pattern("ba", r"(え|け|せ|て|ね|べ|め|れ|げ)ば(?!かり)", "〜ば", "if… (conditional)", "N4", boundary=False),
    Pattern("nara", r"なら", "〜なら", "if it's… / as for…", "N4"),
    Pattern("temo", r"(?<=.)(て|で)も(?!いい|良い|かまわ|構わ)", "〜ても", "even if…", "N4"),
    Pattern("bakari", r"ばかり", "〜ばかり", "nothing but… / just (did)", "N4"),
    Pattern("shikanai", r"しか.{0,12}?(ない|ません|なかった)", "〜しか〜ない", "only… (with a negative verb)", "N4"),
    Pattern("dake", r"だけ", "〜だけ", "only / just", "N5"),
    Pattern("sugiru", r"すぎ|過ぎ", "〜すぎる", "too much…", "N4"),
    Pattern("yasui", r"(やす|にく|づら)(い|く|かっ)", "〜やすい / にくい", "easy to… / hard to…", "N4"),
    Pattern("tekureru", r"(て|で)(くれ|くださ|下さ)", "〜てくれる / てください",
            "someone does it for me / please do…", "N5"),
    Pattern("temorau", r"(て|で)(もら|いただ|頂)", "〜てもらう", "have someone do it (for me)", "N4"),
    Pattern("teageru", r"(て|で)(あげ|さしあげ)", "〜てあげる", "do it for someone", "N4"),
    Pattern("temiru", r"(て|で)み(る|た|ます|よう|て)", "〜てみる", "try doing and see", "N4"),
    Pattern("teoku", r"(て|で)お(く|い|き|こ)", "〜ておく", "do in advance / leave it as is", "N4"),
    Pattern("toshite", r"として", "〜として", "as… (a role or capacity)", "N3"),
    Pattern("nitsuite", r"について|に就いて", "〜について", "about / concerning", "N3"),
    Pattern("niyotte", r"によって|による|により", "〜によって", "by (means / agent); depending on", "N3"),
    Pattern("tte", "", "〜って", "casual quotation: “(someone says) that…” / “speaking of…”", "N3",
            token_check=lambda t: t.surface == "って" and t.pos == "助詞"),
    Pattern("tari", r"(た|だ)り.{0,20}?(た|だ)り(する|し)", "〜たり〜たりする", "do things like… and…", "N4"),
    Pattern("mama", r"まま", "〜まま", "as it is / still (unchanged)", "N3"),
    Pattern("tokoro", r"ところ(だ|です|で|に)", "〜ところ", "about to / in the middle of / just did", "N4"),
    Pattern("beki", r"べき", "〜べき", "should / ought to", "N3"),
    Pattern("zuni", r"ずに", "〜ずに", "without doing… (formal)", "N3"),
    Pattern("naide", r"ないで", "〜ないで", "without doing… / please don't…", "N4"),
    Pattern("nasai", r"なさい", "〜なさい", "do…! (firm command, parent/teacher tone)", "N5"),
    Pattern("masenka", r"ませんか", "〜ませんか", "won't you…? (invitation)", "N5"),
    Pattern("mashou", r"ましょう", "〜ましょう", "let's…", "N5"),
    Pattern("janaika", r"じゃないか|じゃん" + END, "〜じゃないか / じゃん", "isn't it? / you know (seeking agreement)", "N3"),
    Pattern("janai", r"じゃない|ではない|じゃありません|ではありません", "じゃない / ではない", "is not…", "N5"),
    Pattern("kana", r"かな" + END, "〜かな", "I wonder…", "N4"),
    Pattern("noda", r"(の|ん)(だ|です|ですか|か)" + END, "〜のだ / んです", "explaining or emphasizing (“the thing is…”)", "N4"),
    Pattern("hoshii", r"ほしい|欲しい", "〜ほしい / てほしい", "want (something / someone to do)", "N4"),
    Pattern("hougaii", r"(ほう|方)が(いい|良い)", "〜ほうがいい", "had better… / it's better to…", "N4"),
    Pattern("maeni", r"前に|まえに", "〜前に", "before…", "N5"),
    Pattern("atode", r"後で|あとで", "〜後で", "after…", "N5"),
    Pattern("toomou", r"と(思|おも)", "〜と思う", "I think that…", "N4"),
    Pattern("toiu", r"という|っていう|と言う", "〜という", "called… / that says… (quoting)", "N4"),
    Pattern("youtosuru", r"(よ)?うと(する|し)", "〜ようとする", "try to… / be about to…", "N3"),
]
BY_ID = {p.id: p for p in PATTERNS}


def detect(lines: list[list[Token]]) -> list[Match]:
    found: list[Match] = []
    for li, line in enumerate(lines):
        starts, text = [], ""
        for t in line:
            text += t.space_before
            starts.append(len(text))
            text += t.surface
        ends = [s + len(t.surface) for s, t in zip(starts, line)]

        def tokens_for(a: int, b: int) -> tuple[int, int] | None:
            idx = [i for i, (s, e) in enumerate(zip(starts, ends)) if e > a and s < b]
            return (idx[0], idx[-1]) if idx else None

        cands = []
        for p in PATTERNS:
            if p.token_check:
                for i, t in enumerate(line):
                    if p.token_check(t):
                        cands.append((starts[i], ends[i], p))
            else:
                for m in re.finditer(p.regex, text):
                    if m.end() > m.start() and (not p.boundary or m.start() in starts):
                        cands.append((m.start(), m.end(), p))
        cands.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
        taken: list[tuple[int, int]] = []
        for a, b, p in cands:
            if any(a < tb and b > ta for ta, tb in taken):
                continue
            span = tokens_for(a, b)
            if span:
                taken.append((a, b))
                found.append(Match(p, li, span[0], span[1], text[a:b]))
    found.sort(key=lambda m: (m.line, m.first))
    return found


def matches_for(matches: list[Match], lines: list[list[Token]], tok: Token) -> list[Match]:
    out = []
    for m in matches:
        line = lines[m.line] if m.line < len(lines) else []
        if any(t is tok for t in line[m.first:m.last + 1]):
            out.append(m)
    return out
