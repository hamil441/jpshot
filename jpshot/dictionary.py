"""Japanese -> English dictionary: offline JMdict (jamdict) if installed, otherwise jisho.org."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("jpshot.dict")


@dataclass
class Sense:
    glosses: list[str]
    pos: list[str] = field(default_factory=list)


@dataclass
class Entry:
    word: str
    reading: str
    senses: list[Sense]
    common: bool | None = None   # marked as a common word
    jlpt: int | None = None      # 5 (N5, easiest) … 1 (N1)


class Dictionary(QObject):
    # request id, query that matched (or ""), list[Entry], error message ("" if ok)
    finished = Signal(int, str, object, str)
    # request id, {"infos": list[kanji.KanjiInfo], "word", "word_story", "hint"}
    kanji_finished = Signal(int, object)
    # request id, difficulty.Difficulty or None
    difficulty_finished = Signal(int, object)

    def __init__(self, backend: str = "auto"):
        super().__init__()
        self.backend = backend
        # Separate queues so slow background work never delays a word lookup:
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lookup")        # popups
        self._kanji_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kanji")   # breakdowns
        self._story_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="story")   # AI writing
        self._bg_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="difficulty")
        self._cache: dict[str, list[Entry]] = {}
        self._local = threading.local()     # per-thread HTTP session and jamdict connection
        self._jam_failed = backend == "jisho"
        from .kanji import KanjiDB
        self.kanji = KanjiDB(self._http)

    def _http(self):
        import requests

        s = getattr(self._local, "session", None)
        if s is None:
            s = self._local.session = requests.Session()
            s.headers["User-Agent"] = "jpshot (learning tool)"
        return s

    def set_backend(self, backend: str) -> None:
        if backend != self.backend:
            log.info("Dictionary backend -> %s", backend)
            self.backend = backend
            self._jam_failed = backend == "jisho"
            self._cache.clear()

    def estimate_difficulty(self, req_id: int, lines) -> None:
        from .difficulty import estimate

        def entries_for(word):
            try:
                return self._lookup_one(word)
            except Exception:  # noqa: BLE001
                return []

        def job():
            try:
                d = estimate(lines, self.kanji._api, entries_for)
            except Exception:  # noqa: BLE001
                log.exception("Difficulty estimate failed")
                d = None
            self.difficulty_finished.emit(req_id, d)

        self._bg_exec.submit(job)

    def lookup_kanji(self, req_id: int, word: str, candidates: list[str] | None = None) -> None:
        from .kanji import template_word_story

        def job():
            try:
                infos = self.kanji.breakdown(word)
            except Exception:  # noqa: BLE001
                log.exception("Kanji breakdown for %s failed", word)
                infos = []
            meaning, reading = "", ""
            for q in candidates or [word]:
                entries = self._cache.get(q)
                if entries:
                    e = entries[0]
                    reading = e.reading
                    meaning = "; ".join(e.senses[0].glosses[:3]) if e.senses else ""
                    break
            payload = {"infos": infos, "word": word,
                       "word_story": template_word_story(word, meaning, infos),
                       "hint": not self.kanji.has_writer()}
            self.kanji_finished.emit(req_id, payload)
            if infos and self.kanji.has_writer():
                self._story_exec.submit(stories, payload, reading, meaning)

        def stories(payload, reading, meaning):
            # second pass: written explanations, updating the popup as each arrives
            try:
                infos = payload["infos"]
                ws = self.kanji.word_story(word, reading, meaning, infos)
                if ws:
                    payload["word_story"] = ws
                    self.kanji_finished.emit(req_id, payload)
                for k in infos:
                    if not k.story_is_ai:
                        story = self.kanji.story(k)
                        if story:
                            k.story, k.story_is_ai = story, True
                            self.kanji_finished.emit(req_id, payload)
            except Exception:  # noqa: BLE001
                log.exception("Writing explanations for %s failed", word)

        self._kanji_exec.submit(job)

    # -- backends ---------------------------------------------------------
    def _lookup_one(self, q: str) -> list[Entry]:
        if q in self._cache:
            return self._cache[q]
        entries = None
        if not self._jam_failed:
            entries = self._jamdict(q)
        if entries is None:
            entries = self._jisho(q)
        self._cache[q] = entries
        return entries

    def _jamdict(self, q: str) -> list[Entry] | None:
        try:
            jam = getattr(self._local, "jam", None)
            if jam is None:
                from jamdict import Jamdict

                jam = self._local.jam = Jamdict()
                if not getattr(jam, "ready", True):
                    raise RuntimeError("jamdict data not installed")
                log.info("Using offline JMdict (jamdict)")
            try:
                res = jam.lookup(q, lookup_chars=False)
            except TypeError:
                res = jam.lookup(q)
        except Exception as e:  # noqa: BLE001
            if self.backend == "jamdict":
                raise
            log.info("Offline dictionary unavailable (%s); using jisho.org", e)
            self._jam_failed = True
            return None
        out = []
        for ent in res.entries[:3]:
            kanji = [k.text for k in ent.kanji_forms]
            kana = [k.text for k in ent.kana_forms]
            senses = [Sense([g.text for g in s.gloss], list(s.pos)) for s in ent.senses[:5]]
            pri = {p for f in list(ent.kanji_forms) + list(ent.kana_forms) for p in (getattr(f, "pri", None) or [])}
            common = bool(pri & {"news1", "ichi1", "spec1", "spec2", "gai1"})
            out.append(Entry(word=(kanji or kana or [q])[0], reading=(kana or [""])[0], senses=senses,
                             common=common))
        return out

    def _jisho(self, q: str) -> list[Entry]:
        r = self._http().get("https://jisho.org/api/v1/search/words",
                              params={"keyword": q}, timeout=8)
        log.debug("jisho.org %s -> HTTP %s", q, r.status_code)
        r.raise_for_status()
        data = r.json().get("data", [])

        def matches(d):
            return any(j.get("word") == q or j.get("reading") == q for j in d.get("japanese", []))

        chosen = [d for d in data if matches(d)][:3] or data[:2]
        out = []
        for d in chosen:
            j = (d.get("japanese") or [{}])[0]
            senses = [Sense(s.get("english_definitions", []), s.get("parts_of_speech", []))
                      for s in d.get("senses", [])[:5] if s.get("english_definitions")]
            levels = [int(x[-1]) for x in d.get("jlpt", []) if x[-1:].isdigit()]
            out.append(Entry(word=j.get("word") or j.get("reading", q),
                             reading=j.get("reading", ""), senses=senses,
                             common=bool(d.get("is_common")), jlpt=max(levels) if levels else None))
        return out
