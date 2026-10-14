"""OCR with Tesseract: detect whether a screenshot contains Japanese or English text."""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageStat

from .log import short, timed

log = logging.getLogger("jpshot.ocr")

JA_CHARS = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\U00020000-\U0003134f々〆〇"
JA_PUNCT = "、。「」『』（）！？・…〜：；，．"
JA_RE = re.compile(f"[{JA_CHARS}]")
_JA_OR_PUNCT = re.compile(f"[{JA_CHARS}{JA_PUNCT}]")
_SPACE_BETWEEN_JA = re.compile(f"(?<=[{JA_CHARS}{JA_PUNCT}])[ \u3000]+(?=[{JA_CHARS}{JA_PUNCT}])")
LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass
class OcrResult:
    text: str        # line breaks preserved
    language: str    # "ja" or "en"
    confidence: float


def configure(tesseract_cmd: str = "") -> None:
    import pytesseract

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    elif not shutil.which("tesseract"):
        for c in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ):
            if os.path.exists(c):
                pytesseract.pytesseract.tesseract_cmd = c
                break
    cmd = pytesseract.pytesseract.tesseract_cmd
    try:
        version = pytesseract.get_tesseract_version()
        langs = pytesseract.get_languages(config="")
        log.info("Tesseract %s (%s), languages: %s", version, cmd, ", ".join(langs))
        for need in ("jpn", "eng"):
            if need not in langs:
                log.error("Tesseract language data '%s' is missing — install it (see README)", need)
    except Exception as e:  # noqa: BLE001
        log.error("Tesseract not found or not runnable (%s): %s — install it or set tesseract_cmd", cmd, e)


def _prepare(img: Image.Image) -> Image.Image:
    g = img.convert("L")
    if ImageStat.Stat(g).mean[0] < 110:  # light text on dark background
        g = ImageOps.invert(g)
    g = ImageOps.autocontrast(g)
    # Screen text is small; Tesseract likes ~30px glyphs.
    scale = 3 if g.height < 120 else 2 if max(g.size) < 2000 else 1
    if scale > 1:
        g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    return ImageOps.expand(g, border=20, fill=255)


def _join_words(words: list[str]) -> str:
    out = ""
    for w in words:
        if out and not (_JA_OR_PUNCT.match(out[-1]) and _JA_OR_PUNCT.match(w[0])):
            out += " "
        out += w
    return out


def recognize(img: Image.Image, languages: str = "jpn+eng",
              min_conf: int = 55, min_chars: int = 2) -> OcrResult | None:
    """Return the detected text, or None if there is nothing worth translating."""
    import pytesseract

    prepared = _prepare(img)
    log.debug("OCR input %dx%d -> preprocessed %dx%d, lang=%s",
              img.width, img.height, prepared.width, prepared.height, languages)
    with timed(log, "tesseract"):
        data = pytesseract.image_to_data(
            prepared, lang=languages, config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )
    dropped = 0
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if conf < min_conf:
            dropped += 1
            log.debug("  drop %r (conf %.0f < %d)", word, conf, min_conf)
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confs.append(conf)

    text = "\n".join(_join_words(ws) for ws in lines.values())
    text = _SPACE_BETWEEN_JA.sub("", text).strip()

    ja = len(JA_RE.findall(text))
    la = len(LATIN_RE.findall(text))
    log.debug("OCR kept %d words, dropped %d; japanese chars=%d latin chars=%d; text=%r",
              len(confs), dropped, ja, la, text)
    if ja + la < min_chars:
        log.info("No text detected (only %d meaningful chars)", ja + la)
        return None
    lang = "ja" if ja / (ja + la) >= 0.3 else "en"
    if lang == "en":
        text = re.sub(r"(?<!\S)\|(?=\s)", "I", text)  # Tesseract often reads the pronoun "I" as "|"
    if lang == "en" and not re.search(r"[A-Za-z]{2,}", text):
        log.info("No text detected (no English word of 2+ letters)")
        return None
    result = OcrResult(text=text, language=lang, confidence=sum(confs) / len(confs))
    log.info("Detected %s text (avg conf %.0f): %s", "Japanese" if lang == "ja" else "English",
             result.confidence, short(text))
    return result


def flatten(text: str, language: str) -> str:
    """Join wrapped lines so translation / speech treat them as one passage."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return ("" if language == "ja" else " ").join(lines)
