"""Read the text in a screenshot (Japanese or English).

Readers, best first when available:
  * manga-ocr — an AI model made for Japanese; great on stylized and low-resolution game text (optional install)
  * Claude    — online vision model; reads almost anything (optional, uses your API key)
  * Tesseract — always there; JPShot cleans retro pixel fonts up for it first (emulator scale and
                scanlines removed, text separated from the background by color)
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import shutil
import threading
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
    engine: str = "tesseract"   # tesseract | manga-ocr | claude


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


# -- Tesseract ---------------------------------------------------------------------------------------
def _tesseract(prepared: Image.Image, languages: str, min_conf: int) -> tuple[str, list[float], float]:
    """Run Tesseract once. Returns (text, confidences of kept words, score = confident characters)."""
    import pytesseract

    data = pytesseract.image_to_data(prepared, lang=languages, config="--psm 6",
                                     output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    score = 0.0
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if conf < min_conf:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confs.append(conf)
        score += conf / 100 * len(word)
    text = "\n".join(_join_words(ws) for ws in lines.values())
    return _SPACE_BETWEEN_JA.sub("", text).strip(), confs, score


def _quality(text: str, score: float) -> float:
    """Confident characters, discounted when the output looks like symbol soup."""
    chars = text.replace("\n", "").replace(" ", "")
    if not chars:
        return 0.0
    purity = max(len(JA_RE.findall(chars)) + len(re.findall(f"[{JA_PUNCT}ー]", chars)),
                 len(LATIN_RE.findall(chars))) / len(chars)
    return score * purity ** 2


# -- retro / pixel-font cleanup ------------------------------------------------------------------------
def _edge_scale(a, axis: int) -> tuple[int, int]:
    """Emulator integer scale along one axis: pixel blocks only change at one position mod s."""
    import numpy as np

    g = a.astype(np.int32).sum(axis=2)
    d = np.abs(np.diff(g, axis=axis)).sum(axis=0 if axis == 1 else 1)
    if d.max() <= 0:
        return 1, 0
    edges = np.nonzero(d > d.max() * 0.05)[0] + 1
    if len(edges) < 8:
        return 1, 0
    for s in range(6, 1, -1):
        res = np.bincount(edges % s, minlength=s)
        if res.max() / len(edges) > 0.85:
            return s, int(res.argmax())
    return 1, 0


def _native_pixels(img: Image.Image) -> tuple[Image.Image, int]:
    """Undo an emulator's integer upscale (and its scanlines): one sample per original game pixel."""
    import numpy as np

    a = np.asarray(img.convert("RGB"))
    sx, rx = _edge_scale(a, 1)
    sy, _ = _edge_scale(a, 0)
    if sx == 1 and sy == 1:
        return img.convert("RGB"), 1
    sx, sy = max(sx, sy if sx == 1 else sx), max(sy, sx if sy == 1 else sy)   # scanlines hide vertical blocks
    lum = a.astype(np.float32).mean(axis=2)
    py = max(range(sy), key=lambda p: float(lum[p::sy].mean()))   # brightest row phase skips dark scanlines
    px = (rx + sx // 2) % sx
    return Image.fromarray(np.ascontiguousarray(a[py::sy, px::sx])), max(sx, sy)


def _color_masks(img: Image.Image, k: int = 5, keep: int = 2) -> list:
    """Split the picture by color (k-means) and return the masks that look like text, smallest first."""
    import numpy as np

    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    px = a.reshape(-1, 3)
    rng = np.random.default_rng(0)
    sample = px if len(px) <= 30000 else px[rng.choice(len(px), 30000, replace=False)]
    cent = sample[rng.choice(len(sample), k, replace=False)].copy()
    for _ in range(12):
        lab = ((sample[:, None, :] - cent[None]) ** 2).sum(-1).argmin(1)
        for i in range(k):
            m = lab == i
            if m.any():
                cent[i] = sample[m].mean(0)
    lab = ((px[:, None, :] - cent[None]) ** 2).sum(-1).argmin(1).reshape(h, w)
    out = []
    for i in range(k):
        m = lab == i
        cov = float(m.mean())
        border = float(np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]]).mean())
        stripes = float((m.mean(axis=1) > 0.5).mean() + (m.mean(axis=0) > 0.5).mean())   # box lines, textures
        if 0.01 < cov < 0.4 and border < 0.5 and stripes < 0.08:
            out.append((cov, m))
    return [m for _, m in sorted(out, key=lambda t: t[0])][:keep]


def _mask_image(mask, factor: int = 3) -> Image.Image:
    """Black text on white, blocky pixels enlarged and slightly rounded so Tesseract sees strokes."""
    import numpy as np
    from PIL import ImageFilter

    im = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    im = im.resize((im.width * factor, im.height * factor), Image.NEAREST)
    im = im.filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: 0 if v < 128 else 255)
    return ImageOps.expand(im, border=20, fill=255)


def _candidates(img: Image.Image, pixel_fonts: bool, standard_conf: float):
    """Extra cleaned-up versions of the image worth trying for game text."""
    if not pixel_fonts:
        return
    try:
        nat, scale = _native_pixels(img)
        bases = []
        if scale > 1 or max(img.size) <= 500:
            bases.append((nat, f"native pixels (x{scale})" if scale > 1 else "color separated"))
        elif standard_conf < 85:
            # smoothed (bilinear) emulator output: shrink back towards the game's resolution
            bases += [(img.resize((img.width // d, img.height // d), Image.BOX), f"shrunk 1/{d}") for d in (3, 2)]
        for base, name in bases:
            for i, m in enumerate(_color_masks(base, keep=2 if len(bases) == 1 else 1)):
                yield _mask_image(m), f"{name}, text color {i + 1}"
    except Exception:  # noqa: BLE001
        log.exception("Pixel-font cleanup failed; using the plain image")


def _finish(text: str, confs: list[float], min_chars: int, engine: str = "tesseract") -> OcrResult | None:
    ja = len(JA_RE.findall(text))
    la = len(LATIN_RE.findall(text))
    if ja + la < min_chars:
        log.info("No text detected (only %d meaningful chars)", ja + la)
        return None
    lang = "ja" if ja / (ja + la) >= 0.3 else "en"
    if lang == "en":
        text = re.sub(r"(?<!\S)\|(?=\s)", "I", text)  # Tesseract often reads the pronoun "I" as "|"
        if not re.search(r"[A-Za-z]{2,}", text):
            log.info("No text detected (no English word of 2+ letters)")
            return None
    conf = sum(confs) / len(confs) if confs else 0.0
    return OcrResult(text=text, language=lang, confidence=conf, engine=engine)


def recognize(img: Image.Image, languages: str = "jpn+eng", min_conf: int = 55, min_chars: int = 2,
              pixel_fonts: bool = True) -> OcrResult | None:
    """Tesseract, plus retro pixel-font clean-ups when the plain read is weak. None = no text."""
    res, _ = _recognize_tesseract(img, languages, min_conf, min_chars, pixel_fonts)
    return res


def _recognize_tesseract(img, languages, min_conf, min_chars, pixel_fonts):
    """Returns (result, black-on-white image that read best)."""
    prepared = _prepare(img)
    log.debug("OCR input %dx%d -> preprocessed %dx%d, lang=%s",
              img.width, img.height, prepared.width, prepared.height, languages)
    with timed(log, "tesseract"):
        text, confs, score = _tesseract(prepared, languages, min_conf)
    avg = sum(confs) / len(confs) if confs else 0.0
    best = (_quality(text, score), "plain", text, confs, prepared)
    log.debug("  plain: quality %.1f, conf %.0f: %r", best[0], avg, short(text))
    # Pixel fonts read far better with the Japanese model alone (the English one "wins" on blocky
    # glyphs); English game text is retried with every language.
    cand_langs = "jpn" if "jpn" in languages.split("+") else languages
    for cand, name in _candidates(img, pixel_fonts, avg):
        with timed(log, f"tesseract ({name})"):
            t, c, sc = _tesseract(cand, cand_langs, min_conf)
        if cand_langs != languages and len(LATIN_RE.findall(t)) > len(JA_RE.findall(t)):
            t2, c2, sc2 = _tesseract(cand, languages, min_conf)
            if _quality(t2, sc2) > _quality(t, sc):
                t, c, sc = t2, c2, sc2
        q = _quality(t, sc)
        log.debug("  %s: quality %.1f: %r", name, q, short(t))
        if q > best[0]:
            best = (q, name, t, c, cand)
    _, name, text, confs, image = best
    if name != "plain":
        log.info("Pixel-font cleanup helped (%s)", name)
    res = _finish(text, confs, min_chars)
    if res:
        log.info("Detected %s text (avg conf %.0f): %s", "Japanese" if res.language == "ja" else "English",
                 res.confidence, short(res.text))
    return res, image


# -- manga-ocr (optional) ------------------------------------------------------------------------------
_manga = None
_manga_lock = threading.Lock()


def manga_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("manga_ocr") is not None


def warm_up_manga() -> None:
    """Load the model in the background so the first capture isn't slow."""
    if manga_available():
        threading.Thread(target=_get_manga, name="manga-ocr-load", daemon=True).start()


def _get_manga():
    global _manga
    with _manga_lock:
        if _manga is None:
            with timed(log, "loading manga-ocr"):
                from manga_ocr import MangaOcr

                _manga = MangaOcr()
        return _manga


def _text_lines(binary: Image.Image) -> list[Image.Image]:
    """Cut a black-on-white image into text lines (manga-ocr reads one line or bubble at a time)."""
    import numpy as np

    a = np.asarray(binary.convert("L")) < 128
    rows = a.sum(axis=1)
    ink = rows > max(1, a.shape[1] * 0.002)
    lines, start = [], None
    for y, on in enumerate(list(ink) + [False]):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start >= 6:
                lines.append((start, y))
            start = None
    out = []
    for y0, y1 in lines:
        cols = np.nonzero(a[y0:y1].any(axis=0))[0]
        if not len(cols):
            continue
        box = (max(0, cols[0] - 8), max(0, y0 - 6), min(a.shape[1], cols[-1] + 9), min(a.shape[0], y1 + 6))
        out.append(binary.crop(box).convert("RGB"))
    return out


def read_manga(img: Image.Image, binary: Image.Image | None) -> str:
    model = _get_manga()
    lines = _text_lines(binary) if binary is not None else []
    if not lines:
        lines = [img.convert("RGB")]
    with timed(log, f"manga-ocr ({len(lines)} line{'s' if len(lines) != 1 else ''})"):
        texts = [model(line).strip() for line in lines]
    return "\n".join(t for t in texts if t)


# -- Claude (optional, online) ---------------------------------------------------------------------
_CLAUDE_PROMPT = ("This is a screenshot crop, often from a video game. Transcribe ALL the text in it exactly, "
                  "keeping the line breaks. Keep Japanese in Japanese: do not translate, do not add readings or "
                  "romaji, do not fix the grammar. Ignore UI decorations that are not text. If there is no "
                  "readable text, reply with exactly NONE. Reply with the text only.")


def read_claude(img: Image.Image, api_key: str, model: str) -> str:
    import requests

    key = api_key.strip() or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("no Anthropic API key (⚙ Settings → Explanations)")
    pic = img.convert("RGB")
    if max(pic.size) < 600:   # small game crops: enlarge without blurring the pixels
        f = max(2, 600 // max(pic.size))
        pic = pic.resize((pic.width * f, pic.height * f), Image.NEAREST)
    if max(pic.size) > 1568:
        pic.thumbnail((1568, 1568), Image.LANCZOS)
    buf = io.BytesIO()
    pic.save(buf, "PNG")
    body = {"model": model or "claude-haiku-5-5", "max_tokens": 1024, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.b64encode(buf.getvalue()).decode()}},
        {"type": "text", "text": _CLAUDE_PROMPT}]}]}
    with timed(log, "Claude OCR"):
        r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=60,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"Anthropic API HTTP {r.status_code}: {r.text[:200]}")
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
    return "" if text.strip(" .") == "NONE" else text


# -- choosing a reader -------------------------------------------------------------------------------
def read_screenshot(img: Image.Image, cfg) -> OcrResult | None:
    """The OCR entry point: picks the reader(s) from the settings. None = no text (nothing happens)."""
    engine = getattr(cfg, "ocr_engine", "auto")
    min_chars = cfg.ocr_min_chars
    claude_ok = bool(cfg.anthropic_api_key.strip() or os.environ.get("ANTHROPIC_API_KEY"))

    def claude(reason: str) -> OcrResult | None:
        log.info("Reading with Claude (%s)", reason)
        text = read_claude(img, cfg.anthropic_api_key, cfg.story_model)
        return _finish(text, [], min_chars, "claude") if text else None

    if engine == "claude":
        try:
            return claude("chosen in settings")
        except Exception as e:  # noqa: BLE001
            log.warning("Claude OCR failed (%s); using Tesseract", e)

    res, binary = _recognize_tesseract(img, cfg.ocr_languages, cfg.ocr_min_confidence, min_chars,
                                       getattr(cfg, "ocr_pixel_fonts", True))
    fallback = getattr(cfg, "ocr_claude_fallback", False) and claude_ok and engine != "tesseract"

    if res is not None and res.language == "ja" and engine in ("auto", "manga-ocr") and manga_available():
        try:
            text = read_manga(img, binary)
            m = _finish(text, [], min_chars, "manga-ocr") if text else None
            if m is not None and m.language == "ja":
                m.confidence = res.confidence
                log.info("manga-ocr: %s", short(m.text))
                return m
        except Exception as e:  # noqa: BLE001
            log.warning("manga-ocr failed (%s); keeping the Tesseract text", e)

    if fallback and (res is None or res.confidence < 75):
        try:
            c = claude("Tesseract wasn't sure" if res else "Tesseract found nothing")
            if c is not None:
                return c
        except Exception as e:  # noqa: BLE001
            log.warning("Claude OCR failed: %s", e)
    return res


def flatten(text: str, language: str) -> str:
    """Join wrapped lines so translation / speech treat them as one passage."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return ("" if language == "ja" else " ").join(lines)
