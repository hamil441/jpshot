"""English <-> Japanese translation with automatic fallbacks.

Order for backend "google" (the default):
  1. Google's public translate endpoint (translate.googleapis.com, client=gtx)
  2. deep-translator's Google scraper
  3. MyMemory (free API, no key)
  4. Argos (offline, only if installed)
Backend "argos" uses only the offline models.
"""
from __future__ import annotations

import logging
import re
import time

from .log import short

log = logging.getLogger("jpshot.translate")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) jpshot"}
_session = None


def _http():
    global _session
    if _session is None:
        import requests

        _session = requests.Session()
        _session.headers.update(UA)
    return _session


def _chunks(text: str, limit: int) -> list[str]:
    """Split on sentence ends so each piece stays under `limit` characters."""
    if len(text) <= limit:
        return [text]
    parts = re.split(r"(?<=[。！？!?\.])\s*", text)
    out, cur = [], ""
    for p in parts:
        while len(p) > limit:  # one huge sentence: hard split
            out.append(p[:limit])
            p = p[limit:]
        if len(cur) + len(p) > limit and cur:
            out.append(cur)
            cur = ""
        cur += p
    if cur:
        out.append(cur)
    return out


def _gtx(text: str, src: str, dst: str) -> str:
    url = "https://translate.googleapis.com/translate_a/single"
    pieces = []
    for chunk in _chunks(text, 1500):
        params = {"client": "gtx", "sl": src, "tl": dst, "dt": "t"}
        r = _http().post(url, params=params, data={"q": chunk}, timeout=10)
        log.debug("translate.googleapis.com -> HTTP %s", r.status_code)
        r.raise_for_status()
        data = r.json()
        pieces.append("".join(seg[0] for seg in (data[0] or []) if seg and seg[0]))
    out = ("" if dst == "ja" else " ").join(p.strip() for p in pieces)
    if not out.strip():
        raise RuntimeError("empty response")
    return out


def _deep_translator(text: str, src: str, dst: str) -> str:
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source=src, target=dst).translate(text)


def _mymemory(text: str, src: str, dst: str) -> str:
    pieces = []
    for chunk in _chunks(text, 450):
        r = _http().get("https://api.mymemory.translated.net/get",
                        params={"q": chunk, "langpair": f"{src}|{dst}"}, timeout=10)
        log.debug("mymemory -> HTTP %s", r.status_code)
        r.raise_for_status()
        data = r.json()
        if int(data.get("responseStatus", 200)) != 200:
            raise RuntimeError(data.get("responseDetails") or f"status {data.get('responseStatus')}")
        pieces.append(data["responseData"]["translatedText"])
    return ("" if dst == "ja" else " ").join(p.strip() for p in pieces)


def _argos(text: str, src: str, dst: str) -> str:
    import argostranslate.translate

    return argostranslate.translate.translate(text, src, dst)


ENGINES = {"google": _gtx, "google-scraper": _deep_translator, "mymemory": _mymemory, "argos": _argos}


def translate(text: str, src: str, dst: str, backend: str = "google") -> str:
    if not text.strip():
        return ""
    t = time.perf_counter()
    order = ["argos"] if backend == "argos" else ["google", "google-scraper", "mymemory", "argos"]
    if backend in ENGINES and backend not in ("google", "argos"):
        order = [backend] + [o for o in order if o != backend]
    log.debug("Translating %s->%s (try %s): %r", src, dst, " → ".join(order), text)
    errors = []
    for name in order:
        try:
            out = ENGINES[name](text, src, dst)
        except ImportError as e:
            log.debug("%s not installed (%s)", name, e)
            errors.append(f"{name}: not installed")
            continue
        except Exception as e:  # noqa: BLE001
            log.warning("Translator %s failed: %s: %s", name, type(e).__name__, str(e)[:200])
            errors.append(f"{name}: {type(e).__name__}")
            continue
        log.info("Translation %s->%s via %s (%.0f ms): %s", src, dst, name,
                 (time.perf_counter() - t) * 1000, short(out or ""))
        return out
    raise RuntimeError("all translators failed (" + "; ".join(errors) + ")")


def install_offline_models() -> None:
    """Download the Argos en->ja and ja->en models (run once: jpshot --setup-offline)."""
    import argostranslate.package

    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    for src, dst in (("en", "ja"), ("ja", "en")):
        pkg = next((p for p in available if p.from_code == src and p.to_code == dst), None)
        if pkg is None:
            print(f"No Argos package for {src}->{dst}")
            continue
        print(f"Installing {src}->{dst} ...")
        argostranslate.package.install_from_path(pkg.download())
    print('Done. Set "translator": "argos" in config.json to always use offline translation.')


# -- kana → kanji (for an edited Hiragana / Rōmaji box) --------------------------------------------
def kana_to_kanji(kana: str) -> str:
    """Convert hiragana to normal kanji-kana writing with Google's Japanese IME (online).
    Falls back to the kana unchanged; kana is still valid Japanese."""
    import re

    out_lines = []
    for line in kana.split("\n"):
        parts = re.split(r"([。、！？「」『』（）\s]+)", line)   # convert phrase by phrase
        conv = []
        for part in parts:
            if not part or re.fullmatch(r"[。、！？「」『』（）\s]+", part) or not re.search(r"[ぁ-ゖ]", part):
                conv.append(part)
                continue
            try:
                r = _http().get("https://inputtools.google.com/request",
                                params={"text": part, "itc": "ja-t-ja-hira-i0-und", "num": 1,
                                        "cp": 0, "cs": 1, "ie": "utf-8", "oe": "utf-8"}, timeout=8)
                data = r.json()
                cand = data[1][0][1][0] if data and data[0] == "SUCCESS" else ""
                # only accept a candidate that covers the whole phrase
                matched = data[1][0][3].get("matched_length") if len(data[1][0]) > 3 and isinstance(data[1][0][3], dict) else None
                if matched and matched[0] != len(part):
                    cand = ""
                conv.append(cand or part)
            except Exception as e:  # noqa: BLE001
                log.info("Kana → kanji conversion unavailable (%s); keeping kana", e)
                return kana
        out_lines.append("".join(conv))
    out = "\n".join(out_lines)
    log.info("Kana → kanji: %s → %s", short(kana), short(out))
    return out
