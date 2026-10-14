"""Japanese -> English dictionary: offline JMdict (jamdict) if installed, otherwise jisho.org."""
from __future__ import annotations

import logging
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


class Dictionary(QObject):
    # request id, query that matched (or ""), list[Entry], error message ("" if ok)
    finished = Signal(int, str, object, str)
    # request id, list[kanji.KanjiInfo]
    kanji_finished = Signal(int, object)

    def __init__(self, backend: str = "auto"):
        super().__init__()
        self.backend = backend
        # One worker thread: jamdict's SQLite connection must stay on a single thread.
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dict")
        self._cache: dict[str, list[Entry]] = {}
        self._jam = None
        self._jam_failed = backend == "jisho"
        self._session = None
        from .kanji import KanjiDB
        self.kanji = KanjiDB(self._http)

    def _http(self):
        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = "jpshot (learning tool)"
        return self._session

    def set_backend(self, backend: str) -> None:
        if backend != self.backend:
            log.info("Dictionary backend -> %s", backend)
            self.backend = backend
            self._jam_failed = backend == "jisho"
            self._cache.clear()

    def lookup_kanji(self, req_id: int, word: str) -> None:
        def job():
            try:
                infos = self.kanji.breakdown(word)
            except Exception:  # noqa: BLE001
                log.exception("Kanji breakdown for %s failed", word)
                infos = []
            self.kanji_finished.emit(req_id, infos)

        self._exec.submit(job)

    def lookup(self, req_id: int, candidates: list[str]) -> None:
        def job():
            t = time.perf_counter()
            log.debug("Lookup #%d candidates=%s", req_id, candidates)
            try:
                for q in candidates:
                    entries = self._lookup_one(q)
                    if entries:
                        log.info("Lookup %s -> %d entr%s (%.0f ms): %s", q, len(entries),
                                 "y" if len(entries) == 1 else "ies", (time.perf_counter() - t) * 1000,
                                 "; ".join(", ".join(s.glosses[:2]) for e in entries[:1] for s in e.senses[:2]))
                        self.finished.emit(req_id, q, entries, "")
                        return
                log.info("Lookup %s -> no entries", candidates)
                self.finished.emit(req_id, "", [], "")
            except Exception as e:  # noqa: BLE001
                log.exception("Lookup %s failed", candidates)
                self.finished.emit(req_id, "", [], f"{type(e).__name__}: {e}")

        self._exec.submit(job)

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
            if self._jam is None:
                from jamdict import Jamdict

                self._jam = Jamdict()
                if not getattr(self._jam, "ready", True):
                    raise RuntimeError("jamdict data not installed")
                log.info("Using offline JMdict (jamdict)")
            try:
                res = self._jam.lookup(q, lookup_chars=False)
            except TypeError:
                res = self._jam.lookup(q)
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
            out.append(Entry(word=(kanji or kana or [q])[0], reading=(kana or [""])[0], senses=senses))
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
            out.append(Entry(word=j.get("word") or j.get("reading", q),
                             reading=j.get("reading", ""), senses=senses))
        return out
