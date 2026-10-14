"""Grammar explanations for learners: word roles, particles, conjugations and verb-phrase meaning.

Uses UniDic features from the tokenizer (part of speech, conjugation type/form, lemma).
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field

from .japanese import Token

# part of speech -> (English name, color, short explanation)
POS = {
    "名詞": ("Noun", "#4e9af1", "a thing, person, place or idea"),
    "代名詞": ("Pronoun", "#4e9af1", "stands in for a noun (I, you, this, that…)"),
    "動詞": ("Verb", "#e8556d", "an action or state"),
    "形容詞": ("い-adjective", "#f0a030", "describes a noun; conjugates itself (past, negative…)"),
    "形状詞": ("な-adjective", "#e8a33d", "describes a noun; takes な before nouns, だ/です at the end"),
    "副詞": ("Adverb", "#b07ce8", "modifies a verb, adjective or the whole sentence"),
    "連体詞": ("Pre-noun adjectival", "#d18a3a", "only ever comes right before a noun (この, その, ある…)"),
    "接続詞": ("Conjunction", "#8e9aa8", "links sentences or clauses (でも, そして…)"),
    "感動詞": ("Interjection", "#8e9aa8", "an exclamation or greeting"),
    "助詞": ("Particle", "#2fb383", "a small word that marks the role of what comes before it"),
    "助動詞": ("Auxiliary", "#d65db1", "a helper attached to a verb/adjective: tense, politeness, negation…"),
    "接頭辞": ("Prefix", "#8e9aa8", "attaches to the front of a word"),
    "接尾辞": ("Suffix", "#7aa5c9", "attaches to the end of a word (さん, たち, 的…)"),
    "補助記号": ("Punctuation", "#8e9aa8", ""),
    "記号": ("Symbol", "#8e9aa8", ""),
}
LEGEND = ["名詞", "動詞", "形容詞", "形状詞", "副詞", "助詞", "助動詞", "接尾辞"]

PARTICLES = {
    "は": "Topic marker (read “wa”): what the sentence is about — “as for X…”",
    "が": "Subject marker: who/what does the action or has the quality; also “but” between clauses",
    "を": "Direct-object marker (read “o”): what the action is done to",
    "に": "Target / time / place of existence: to, at, in, on (a time), for",
    "で": "Place of action, or means: at/in (where it happens), by/with (how)",
    "へ": "Direction marker (read “e”): toward",
    "と": "“and” (complete list), “with” (together), or quotation “that…”",
    "の": "Possessive / linking (“X's”, “X of Y”), or turns a clause into a noun",
    "も": "“also / too”; with numbers or negatives “even, as many as”",
    "か": "Question marker; between nouns “or”",
    "から": "“from” (starting point), or after a clause “because”",
    "まで": "“until / up to / as far as”",
    "より": "“than” (comparison) or formal “from”",
    "や": "“and” for a non-complete list (… and so on)",
    "ね": "Sentence end: seeks agreement — “right? / isn't it?”",
    "よ": "Sentence end: emphasis / telling new information — “you know”",
    "て": "Te-form connector: “and (then)”, or links to a helper verb (〜ている, 〜てください…)",
    "で ": "Te-form connector (voiced て)",
    "ば": "Conditional: “if …”",
    "けど": "“but / although” (casual)",
    "けれど": "“but / although”",
    "けれども": "“but / although” (polite)",
    "のに": "“even though / despite” (often with frustration)",
    "ので": "“because / so” (softer, explanatory)",
    "し": "Lists reasons: “and also… (so)”",
    "たり": "Lists example actions: “do things like … and …”",
    "ながら": "“while (doing)” — two actions at once",
    "でも": "“even / or something”",
    "だけ": "“only / just”",
    "しか": "“only / nothing but” (always with a negative verb)",
    "ばかり": "“nothing but / just (did)”",
    "など": "“etc. / things like”",
    "って": "Casual quotation or topic: “(they said) that… / speaking of…”",
    "な": "Sentence end after a dictionary-form verb: prohibition “don't!”; otherwise emotive",
    "わ": "Sentence end: soft emphasis",
    "ぞ": "Sentence end: strong emphasis",
    "ぜ": "Sentence end: casual emphasis",
    "さ": "Sentence end: casual assertion",
    "ほど": "“to the extent of / about”",
    "くらい": "“about / approximately / at least”",
    "ぐらい": "“about / approximately / at least”",
    "とか": "“things like / or something”",
    "かな": "Sentence end: “I wonder…”",
}

# auxiliary verbs keyed by lemma
AUX = {
    "た": ("past", "Past / completed — “did”"),
    "ます": ("polite", "Polite ending (〜ます)"),
    "です": ("polite", "Polite copula “is / am / are” (です)"),
    "だ": ("copula", "Plain copula “is / am / are” (だ)"),
    "ない": ("negative", "Negative — “not”"),
    "ぬ": ("negative", "Negative (formal/old: ぬ, ず, ん in ません)"),
    "たい": ("want", "Desire — “want to …”"),
    "れる": ("passive", "Passive / potential / honorific (れる)"),
    "られる": ("passive", "Passive / potential / honorific (られる)"),
    "せる": ("causative", "Causative — “make/let someone …”"),
    "させる": ("causative", "Causative — “make/let someone …”"),
    "う": ("volitional", "Volitional — “let's … / I'll …”"),
    "よう": ("volitional", "Volitional — “let's … / I'll …”"),
    "まい": ("neg-volitional", "Negative volitional — “will not / probably not”"),
    "らしい": ("hearsay", "“seems / apparently”"),
    "そうだ": ("hearsay", "“looks like / I heard that”"),
    "ようだ": ("seems", "“seems / appears”"),
    "べし": ("should", "“should / must”"),
}

# helper verbs after the te-form, keyed by UniDic lemma
TE_HELPERS = {
    "居る": ("progressive", "〜ている: ongoing action (“is …ing”) or resulting state"),
    "有る": ("resultant", "〜てある: something was done and remains that way"),
    "仕舞う": ("completive", "〜てしまう: finish completely / do by mistake (regret)"),
    "置く": ("preparatory", "〜ておく: do in advance / leave as is"),
    "見る": ("attempt", "〜てみる: try doing and see"),
    "来る": ("come", "〜てくる: come to / start to / go and come back"),
    "行く": ("go", "〜ていく: continue on / go on doing"),
    "呉れる": ("favor-to-me", "〜てくれる: someone does it for me"),
    "貰う": ("receive-favor", "〜てもらう: have someone do it for me"),
    "上げる": ("favor-to-other", "〜てあげる: do it for someone"),
    "下さる": ("request", "〜てください: please do"),
}

CTYPE = {
    "五段": "godan verb (う-verb): stem changes across a-i-u-e-o",
    "上一段": "ichidan verb (る-verb): drop る to conjugate",
    "下一段": "ichidan verb (る-verb): drop る to conjugate",
    "カ行変格": "irregular verb (来る)",
    "サ行変格": "irregular verb (する)",
    "形容詞": "い-adjective",
}

CFORM = {
    "終止形": "dictionary (plain, sentence-ending) form",
    "連体形": "attributive form — modifies the noun after it",
    "連用形": "continuative stem — joins ます, た, て, たい…",
    "未然形": "negative base — joins ない, (よ)う, れる…",
    "仮定形": "conditional base — joins ば",
    "命令形": "imperative — a command",
    "意志推量形": "volitional — “let's …”",
    "語幹": "stem",
}

PHRASE_LABELS = {
    "past": "past", "polite": "polite", "negative": "negative", "want": "want to",
    "passive": "passive/potential", "causative": "causative", "volitional": "volitional",
    "progressive": "ongoing (〜ている)", "te": "te-form (connecting)", "conditional": "conditional",
    "completive": "completed (〜てしまう)", "attempt": "try (〜てみる)", "request": "request (〜ください)",
    "copula": "plain “is”", "resultant": "resultant state", "preparatory": "in advance",
}


@dataclass
class Info:
    role: str
    color: str
    role_note: str
    details: list[str] = field(default_factory=list)
    phrase: str = ""
    phrase_summary: str = ""


def color_for(tok: Token) -> str | None:
    if not tok.lookupable:
        return None
    return POS.get(tok.pos, ("", "#8e9aa8", ""))[1]


def _attaches(prev: Token, tok: Token) -> bool:
    """Does `tok` continue the verb/adjective phrase that ends with `prev`?"""
    if tok.pos == "助動詞":
        return prev.pos not in ("補助記号", "記号")
    if tok.pos == "接尾辞" and prev.pos in ("動詞", "形容詞", "助動詞"):
        return True
    if tok.pos == "助詞" and tok.surface in ("て", "で", "ば") and prev.pos in ("動詞", "形容詞", "助動詞"):
        return True
    if tok.pos in ("動詞", "形容詞") and prev.surface in ("て", "で") and tok.lemma in TE_HELPERS:
        return True
    if tok.pos == "形容詞" and tok.lemma in ("無い",) and prev.pos in ("形容詞", "動詞"):
        return True
    return False


def _joins_suru(line: list[Token], k: int) -> bool:
    """Is line[k] a する verb directly after a noun (勉強 + する)?"""
    return 0 < k < len(line) and line[k].lemma == "為る" and line[k - 1].pos == "名詞"


def _phrase(line: list[Token], i: int) -> tuple[int, int]:
    """Indices [start, end) of the predicate phrase containing token i (or (i, i+1))."""
    start = i
    while start > 0 and (_attaches(line[start - 1], line[start]) or _joins_suru(line, start)):
        start -= 1
    end = start + 1
    while end < len(line) and (_attaches(line[end - 1], line[end]) or _joins_suru(line, end)):
        end += 1
    if end - start == 1:
        return i, i + 1
    return start, end


def _summarize(toks: list[Token]) -> str:
    flags: list[str] = []

    def add(f):
        if f not in flags:
            flags.append(f)

    for j, t in enumerate(toks):
        if t.pos == "助動詞":
            key = t.lemma or t.surface
            if key in AUX:
                add(AUX[key][0])
        elif t.pos == "助詞" and t.surface in ("て", "で"):
            if j == len(toks) - 1:
                add("te")
        elif t.pos == "助詞" and t.surface == "ば":
            add("conditional")
        elif j > 0 and toks[j - 1].surface in ("て", "で") and t.lemma in TE_HELPERS:
            add(TE_HELPERS[t.lemma][0])
        elif t.pos == "形容詞" and t.lemma == "無い" and j > 0:
            add("negative")
    head = toks[0]
    if head.pos == "形容詞" and head.cform.startswith("連用形") and len(toks) > 1 and toks[1].lemma == "た":
        add("past")
    tense = "past" if "past" in flags else ("" if {"te", "volitional", "request"} & set(flags) else "present")
    labels = [PHRASE_LABELS.get(f, f) for f in flags if f != "past"]
    parts = ([tense] if tense else []) + labels
    if "polite" not in flags and head.pos in ("動詞", "形容詞") and tense:
        parts.append("plain")
    return " · ".join(parts)


def describe(lines: list[list[Token]], tok: Token) -> Info:
    name, color, note = POS.get(tok.pos, (tok.pos or "Word", "#8e9aa8", ""))
    info = Info(role=name, color=color, role_note=note)

    if tok.pos == "助詞":
        expl = PARTICLES.get(tok.surface)
        if tok.surface == "が" and tok.pos2 == "接続助詞":
            expl = "“but” — joins two clauses"
        if expl:
            info.details.append(expl)
    elif tok.pos == "助動詞":
        key = tok.lemma or tok.surface
        if key in AUX:
            info.details.append(AUX[key][1])
    elif tok.pos in ("動詞", "形容詞"):
        for prefix, expl in CTYPE.items():
            if tok.ctype.startswith(prefix):
                info.details.append(f"Type: {expl}")
                break
        if tok.lemma in TE_HELPERS and tok.pos2 == "非自立可能":
            info.details.append(TE_HELPERS[tok.lemma][1])
    if tok.cform and tok.pos in ("動詞", "形容詞", "助動詞"):
        base = tok.cform.split("-")[0]
        if base in CFORM:
            info.details.append(f"Form: {base} — {CFORM[base]}")

    # find the token's line and position, then its phrase
    for line in lines:
        for i, t in enumerate(line):
            if t is tok:
                s, e = _phrase(line, i)
                if e - s > 1 or line[s].pos in ("動詞", "形容詞"):
                    toks = line[s:e]
                    info.phrase = "".join(t.surface for t in toks)
                    info.phrase_summary = _summarize(toks)
                return info
    return info


def to_html(info: Info) -> str:
    h = (f"<div style='margin-top:6px'><span style='background:{info.color};color:white;"
         f"padding:1px 6px;border-radius:3px'>&nbsp;{html.escape(info.role)}&nbsp;</span>")
    if info.role_note:
        h += f" <span style='color:gray'>{html.escape(info.role_note)}</span>"
    h += "</div>"
    for d in info.details:
        h += f"<div>• {html.escape(d)}</div>"
    if info.phrase and info.phrase_summary:
        h += (f"<div style='margin-top:4px'>Phrase <b>{html.escape(info.phrase)}</b>: "
              f"<span style='color:#d65db1'>{html.escape(info.phrase_summary)}</span></div>")
    return h


def legend_html() -> str:
    return ("  ".join(f"<span style='color:{POS[k][1]}'>■</span> {POS[k][0]}" for k in LEGEND)
            + "  ·  plain = symbols, numbers, non-Japanese")
