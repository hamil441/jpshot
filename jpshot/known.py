"""Words (and kanji) you already know: marked by hand and/or synced from your Anki reviews.

Stored in known.json next to config.json:
  {"known": [...], "unknown": [...], "anki": [...], "kanji": "…"}
"known"/"unknown" are your manual marks (they win over Anki); "anki" is replaced on each sync.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from .config import config_dir
from .japanese import Token
from .kanji import is_kanji

log = logging.getLogger("jpshot.known")

CONTENT_POS = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "接尾辞"}
_TAGS = re.compile(r"<[^>]+>|\[[^\]]*\]|&nbsp;|\{\{c\d+::|\}\}")
_RUBY = re.compile(r"\s*([^\s\[\]]+?)\[([^\]]+)\]")
_JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff々〆]")
READING_FIELDS = ("word furigana", "word reading", "vocabulary-furigana", "vocabulary-kana", "furigana",
                  "reading", "vocab furigana", "vocabfurigana", "kana")


def reading_from_furigana(value: str) -> str:
    """'分[わ]かる' or '<b>食[た]べる</b>' -> 'わかる' / 'たべる' (kana only, '' if it isn't)."""
    v = re.sub(r"<[^>]+>|&nbsp;", "", value)
    v = _RUBY.sub(lambda m: m.group(2), v).replace(" ", "").strip()
    from .japanese import kata_to_hira
    v = kata_to_hira(v)
    return v if v and all("\u3040" <= c <= "\u309f" or c == "ー" for c in v) else ""


def clean_field(value: str) -> str:
    """Anki field -> plain word (strip HTML, furigana brackets, cloze markers, spaces)."""
    return _TAGS.sub("", value).replace(" ", "").strip()


class KnownWords:
    def __init__(self):
        self.path = config_dir() / "known.json"
        self._lock = threading.Lock()
        self.known: set[str] = set()
        self.unknown: set[str] = set()
        self.anki: set[str] = set()
        self.anki_kana: set[str] = set()   # readings of known words (match words written in kana)
        self.last_sync = ""
        self.extra_kanji = ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.known = set(data.get("known", []))
            self.unknown = set(data.get("unknown", []))
            self.anki = set(data.get("anki", []))
            self.anki_kana = set(data.get("anki_kana", []))
            self.last_sync = data.get("last_sync", "")
            self.extra_kanji = data.get("kanji", "")
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("Could not read %s: %s", self.path, e)
        self._kanji_cache: set[str] | None = None

    def save(self):
        with self._lock:
            self.path.write_text(json.dumps({"known": sorted(self.known), "unknown": sorted(self.unknown),
                                             "anki": sorted(self.anki), "anki_kana": sorted(self.anki_kana),
                                             "last_sync": self.last_sync, "kanji": self.extra_kanji},
                                            ensure_ascii=False, indent=0), encoding="utf-8")
        self._kanji_cache = None

    # -- queries ----------------------------------------------------------
    @staticmethod
    def counts(tok: Token) -> bool:
        """Is this a word worth tracking (not a particle, symbol or non-Japanese)?"""
        return tok.lookupable and tok.pos in CONTENT_POS

    def is_known(self, tok: Token) -> bool:
        from .japanese import has_kanji, kata_to_hira

        keys = {tok.base, tok.surface, tok.lemma} - {""}
        if keys & self.unknown:
            return False
        if keys & (self.known | self.anki):
            return True
        # a word written in kana (わかる) counts if you know it written with kanji (分かる)
        if not has_kanji(tok.surface):
            kana = {kata_to_hira(k) for k in keys if not has_kanji(k)}
            return bool(kana & self.anki_kana)
        return False

    def unknown_words(self, lines) -> list[Token]:
        seen, out = set(), []
        for line in lines:
            for t in line:
                if self.counts(t) and not self.is_known(t) and t.base not in seen:
                    seen.add(t.base)
                    out.append(t)
        return out

    def is_known_word(self, word: str) -> bool:
        if word in self.unknown:
            return False
        return word in self.known or word in self.anki

    def mark_word(self, word: str, known: bool = True):
        if known:
            self.unknown.discard(word)
            self.known.add(word)
        else:
            self.known.discard(word)
            self.unknown.add(word)
        self.save()

    def known_kanji(self) -> set[str]:
        if self._kanji_cache is None:
            ks = {c for w in (self.known | self.anki) - self.unknown for c in w if is_kanji(c)}
            ks |= {c for c in self.extra_kanji if is_kanji(c)}
            self._kanji_cache = ks
        return self._kanji_cache

    def total(self) -> int:
        return len((self.known | self.anki) - self.unknown)

    # -- marking ----------------------------------------------------------
    def toggle(self, tok: Token) -> bool:
        """Flip known/unknown for a word; returns the new state."""
        key = tok.base or tok.surface
        if self.is_known(tok):
            self.known.discard(key)
            self.unknown.add(key)
            state = False
        else:
            self.unknown.discard(key)
            self.known.add(key)
            state = True
        self.save()
        log.info("Marked %s as %s", key, "known" if state else "unknown")
        return state

    def set_extra_kanji(self, text: str):
        self.extra_kanji = "".join(dict.fromkeys(c for c in text if is_kanji(c)))
        self.save()

    # -- Anki sync --------------------------------------------------------
    def sync_from_anki(self, url: str, query: str, fields: list[str]) -> dict:
        """Collect words from reviewed (not new) Anki notes.

        Uses the named word fields; for note types that have none of them, falls back to the
        note's first field when it looks like a single Japanese word. Returns a report dict.
        """
        import time

        from . import anki

        q = f"({query}) -is:new" if query.strip() else "-is:new"
        note_ids = anki.invoke(url, "findNotes", query=q)
        words: set[str] = set()
        kana: set[str] = set()
        wanted = [f.strip().lower() for f in fields if f.strip()]
        used_fields: dict[str, int] = {}
        skipped_types: dict[str, list[str]] = {}
        for i in range(0, len(note_ids), 500):
            for note in anki.invoke(url, "notesInfo", notes=note_ids[i:i + 500]):
                nf = note.get("fields", {})
                by_lower = {name.lower(): name for name in nf}
                found = [by_lower[w] for w in wanted if w in by_lower]
                if not found and nf:
                    first = min(nf, key=lambda n: nf[n].get("order", 0))
                    w = clean_field(nf[first].get("value", ""))
                    if w and len(w) <= 12 and _JP.search(w):
                        found = [first]
                    else:
                        skipped_types.setdefault(note.get("modelName", "?"), list(nf))
                        continue
                for name in found:
                    w = clean_field(nf[name].get("value", ""))
                    if w and len(w) <= 20 and _JP.search(w):
                        words.add(w)
                        used_fields[name] = used_fields.get(name, 0) + 1
                for low in READING_FIELDS:
                    if low in by_lower:
                        r = reading_from_furigana(nf[by_lower[low]].get("value", ""))
                        if r:
                            kana.add(r)
                        break
        self.anki = words
        self.anki_kana = kana | {w for w in words if all("\u3040" <= c <= "\u30ff" or c == "ー" for c in w)}
        self.last_sync = time.strftime("%Y-%m-%d %H:%M")
        self.save()
        report = {"notes": len(note_ids), "words": len(words), "fields": used_fields,
                  "skipped": skipped_types, "query": q}
        log.info("Synced %d known words from %d reviewed Anki notes (fields: %s)%s", len(words), len(note_ids),
                 ", ".join(f"{k}×{v}" for k, v in used_fields.items()) or "none",
                 f"; skipped note types: {', '.join(skipped_types)}" if skipped_types else "")
        return report


def describe_report(r: dict, total: int) -> str:
    if r["notes"] == 0:
        return (f"No reviewed notes found for “{r['query']}”. Is Anki open, and does the Anki search match "
                f"your deck (e.g. deck:Kaishi*)?")
    msg = f"Synced {r['words']:,} words from {r['notes']:,} reviewed notes"
    if r["fields"]:
        msg += " (field " + ", ".join(r["fields"]) + ")"
    msg += f" · {total:,} known in total"
    if r["skipped"]:
        kinds = "; ".join(f"{m}: {', '.join(f[:5])}" for m, f in list(r["skipped"].items())[:2])
        msg += f".  Skipped note types with no word field — add one of their field names: {kinds}"
    return msg
