"""Conjugation tables for verbs and adjectives, from the dictionary form and UniDic's conjugation type."""
from __future__ import annotations

# godan ending -> (a, i, e, o) row kana
GODAN = {
    "う": ("わ", "い", "え", "お"), "く": ("か", "き", "け", "こ"), "ぐ": ("が", "ぎ", "げ", "ご"),
    "す": ("さ", "し", "せ", "そ"), "つ": ("た", "ち", "て", "と"), "ぬ": ("な", "に", "ね", "の"),
    "ぶ": ("ば", "び", "べ", "ぼ"), "む": ("ま", "み", "め", "も"), "る": ("ら", "り", "れ", "ろ"),
}
TE = {"う": "って", "つ": "って", "る": "って", "む": "んで", "ぶ": "んで", "ぬ": "んで",
      "く": "いて", "ぐ": "いで", "す": "して"}


def _past(te: str) -> str:
    return te[:-1] + ("だ" if te.endswith("で") else "た")


def verb_class(base: str, ctype: str, pos: str) -> str | None:
    if pos == "形容詞" or ctype.startswith("形容詞"):
        return "i-adj"
    if pos == "形状詞":
        return "na-adj"
    if ctype.startswith("サ行変格") or base.endswith("する") or base == "為る":
        return "suru"
    if ctype.startswith("カ行変格") or base in ("来る", "くる"):
        return "kuru"
    if ctype.startswith(("上一段", "下一段")):
        return "ichidan"
    if ctype.startswith("五段") and base[-1:] in GODAN:
        return "godan"
    return None


def conjugations(base: str, ctype: str, pos: str) -> list[tuple[str, str]]:
    """[(label, form)] for the main forms a learner meets; [] if the word doesn't conjugate."""
    kind = verb_class(base, ctype, pos)
    if not kind or not base:
        return []
    if kind == "i-adj":
        stem = "よ" if base in ("いい", "良い") and base == "いい" else base[:-1]
        if base == "良い":
            stem = "良"
        return [("polite", base + "です"), ("negative", stem + "くない"), ("past", stem + "かった"),
                ("past negative", stem + "くなかった"), ("te-form", stem + "くて"),
                ("adverb", stem + "く"), ("if", stem + "ければ")]
    if kind == "na-adj":
        return [("before a noun", base + "な"), ("is", base + "だ"), ("polite", base + "です"),
                ("negative", base + "じゃない"), ("past", base + "だった"), ("te-form", base + "で"),
                ("adverb", base + "に")]
    if kind == "suru":
        pre = base[:-2] if base.endswith("する") else ""
        forms = [("polite", "します"), ("negative", "しない"), ("past", "した"), ("past negative", "しなかった"),
                 ("te-form", "して"), ("potential", "できる"), ("passive", "される"), ("causative", "させる"),
                 ("volitional", "しよう"), ("if", "すれば"), ("command", "しろ")]
        return [(lab, pre + f) for lab, f in forms]
    if kind == "kuru":
        k = "来" if base.startswith("来") else ""
        r = (lambda kanji, kana: (k + kanji) if k else kana)
        return [("polite", r("ます", "きます")), ("negative", r("ない", "こない")), ("past", r("た", "きた")),
                ("past negative", r("なかった", "こなかった")), ("te-form", r("て", "きて")),
                ("potential", r("られる", "こられる")), ("volitional", r("よう", "こよう")),
                ("if", r("れば", "くれば")), ("command", r("い", "こい"))]
    if kind == "ichidan":
        s = base[:-1]
        return [("polite", s + "ます"), ("negative", s + "ない"), ("past", s + "た"),
                ("past negative", s + "なかった"), ("te-form", s + "て"), ("potential", s + "られる"),
                ("passive", s + "られる"), ("causative", s + "させる"), ("volitional", s + "よう"),
                ("if", s + "れば"), ("command", s + "ろ")]
    # godan
    s, end = base[:-1], base[-1]
    a, i, e, o = GODAN[end]
    te = s + TE[end]
    if base in ("行く", "いく"):
        te = s + "って"
    neg = s + a + "ない"
    if base in ("ある", "有る"):
        neg = "ない"
    return [("polite", s + i + "ます"), ("negative", neg), ("past", _past(te)),
            ("past negative", neg[:-1] + "かった"), ("te-form", te), ("potential", s + e + "る"),
            ("passive", s + a + "れる"), ("causative", s + a + "せる"), ("volitional", s + o + "う"),
            ("if", s + e + "ば"), ("command", s + e)]


def table_html(rows: list[tuple[str, str]]) -> str:
    import html

    if not rows:
        return ""
    cells = " · ".join(f"<span style='color:gray'>{html.escape(lab)}</span> {html.escape(form)}"
                       for lab, form in rows)
    return f"<div style='margin-top:4px;font-size:10pt'><b>Forms:</b> {cells}</div>"
