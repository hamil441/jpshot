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
        self.extra_kanji = ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.known = set(data.get("known", []))
            self.unknown = set(data.get("unknown", []))
            self.anki = set(data.get("anki", []))
            self.extra_kanji = data.get("kanji", "")
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("Could not read %s: %s", self.path, e)
        self._kanji_cache: set[str] | None = None

    def save(self):
        with self._lock:
            self.path.write_text(json.dumps({"known": sorted(self.known), "unknown": sorted(self.unknown),
                                             "anki": sorted(self.anki), "kanji": self.extra_kanji},
                                            ensure_ascii=False, indent=0), encoding="utf-8")
        self._kanji_cache = None

    # -- queries ----------------------------------------------------------
    @staticmethod
    def counts(tok: Token) -> bool:
        """Is this a word worth tracking (not a particle, symbol or non-Japanese)?"""
        return tok.lookupable and tok.pos in CONTENT_POS

    def is_known(self, tok: Token) -> bool:
        keys = {tok.base, tok.surface, tok.lemma} - {""}
        if keys & self.unknown:
            return False
        return bool(keys & (self.known | self.anki))

    def unknown_words(self, lines) -> list[Token]:
        seen, out = set(), []
        for line in lines:
            for t in line:
                if self.counts(t) and not self.is_known(t) and t.base not in seen:
                    seen.add(t.base)
                    out.append(t)
        return out

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
    def sync_from_anki(self, url: str, query: str, fields: list[str]) -> int:
        """Collect words from the given fields of reviewed (not new) Anki notes."""
        from . import anki

        q = f"({query}) -is:new" if query.strip() else "-is:new"
        note_ids = anki.invoke(url, "findNotes", query=q)
        words: set[str] = set()
        wanted = {f.strip().lower() for f in fields if f.strip()}
        for i in range(0, len(note_ids), 500):
            for note in anki.invoke(url, "notesInfo", notes=note_ids[i:i + 500]):
                for name, f in note.get("fields", {}).items():
                    if name.lower() in wanted:
                        w = clean_field(f.get("value", ""))
                        if w and len(w) <= 20:
                            words.add(w)
        self.anki = words
        self.save()
        log.info("Synced %d known words from %d reviewed Anki notes", len(words), len(note_ids))
        return len(words)
