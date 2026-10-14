"""Kanji breakdown in the spirit of Remembering the Kanji: keyword, meanings, readings, components.

Data sources (downloaded on first use, cached in ~/.cache/jpshot):
  * KanjiVG (Ulrich Apel, CC BY-SA 3.0): stroke data split into components with positions,
    used to draw each part in its own color
  * KRADFILE (EDRDG, CC BY-SA 4.0): component lists when KanjiVG has no split
  * kanjiapi.dev: meanings, readings, grade/JLPT and the Heisig (RTK) keyword
  * Wiktionary: glyph origin (why the parts make the character)
  * optional: the Anthropic API writes a short RTK-style story (needs an API key)
"""
from __future__ import annotations

import gzip
import html
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("jpshot.kanji")

KRAD_URLS = [
    "http://ftp.edrdg.org/pub/Nihongo/kradfile.gz",
    "https://ftp.edrdg.org/pub/Nihongo/kradfile.gz",
    "http://ftp.monash.edu/pub/nihongo/kradfile.gz",
]
KRAD2_URLS = [u.replace("kradfile.gz", "kradfile2.gz") for u in KRAD_URLS]

# Names for components that aren't ordinary kanji (or whose radical meaning differs),
# mostly following RTK primitive names. KRADFILE writes several radicals using stand-in
# kanji (化 for 亻, 汁 for 氵 …); those are mapped here too.
RADICALS = {
    "亻": "person", "化": "person", "氵": "water", "汁": "water", "扌": "fingers / hand",
    "扎": "fingers / hand", "艹": "flowers / grass", "艾": "flowers / grass",
    "忄": "state of mind", "忙": "state of mind", "辶": "road / movement", "込": "road / movement",
    "阝": "pinnacle / city", "阡": "pinnacle", "邦": "city", "犭": "pack of wild dogs",
    "犯": "pack of wild dogs", "礻": "altar / spirit", "礼": "altar / spirit", "衤": "cloak",
    "初": "cloak", "宀": "house / roof", "冖": "crown / cover", "⺌": "little", "尚": "little",
    "灬": "oven fire", "杰": "oven fire", "刂": "saber / knife", "刈": "saber / knife",
    "亠": "top hat / lid", "儿": "human legs", "冂": "hood", "几": "wind / table", "凵": "container",
    "勹": "bound up / wrapping", "匕": "spoon / sitting", "匚": "box", "卩": "stamp / seal",
    "厶": "elbow / private", "又": "crotch / again / right hand", "囗": "enclosure", "夂": "walking legs",
    "彡": "hair / shape", "彳": "going person", "疒": "sickness", "广": "cave / dotted cliff",
    "厂": "cliff", "尸": "flag / corpse", "戸": "door", "廴": "stretch", "廾": "two hands",
    "弋": "arrow / ceremony", "彐": "broom", "ヨ": "broom", "攵": "taskmaster", "攴": "taskmaster",
    "丶": "drop", "丿": "slash", "乙": "fishhook", "乚": "fishhook", "亅": "barb", "丨": "walking stick",
    "一": "one / floor", "ノ": "slash", "ハ": "animal legs / eight", "マ": "mama", "ユ": "yu",
    "个": "umbrella", "𠆢": "umbrella", "⺍": "little", "龸": "school house", "⺈": "bound up",
    "罒": "eye (sideways) / net", "買": "net", "⺮": "bamboo", "竹": "bamboo", "糸": "thread",
    "言": "say / words", "金": "gold / metal", "食": "eat / food", "飠": "eat / food",
    "月": "moon / month / flesh (part of body)", "日": "sun / day", "曰": "say", "口": "mouth",
    "木": "tree / wood", "火": "fire", "土": "soil / ground", "士": "samurai / gentleman",
    "心": "heart", "女": "woman", "子": "child", "人": "person", "手": "hand", "目": "eye",
    "田": "rice field", "力": "power", "刀": "sword / knife", "王": "king / jewel", "玉": "jewel",
    "石": "stone", "示": "altar / show", "禾": "grain / wheat", "穴": "hole", "立": "stand / vase",
    "羊": "sheep", "耳": "ear", "虫": "insect", "衣": "garment", "見": "see", "足": "foot / leg",
    "走": "run", "酉": "sake jar / whiskey bottle", "雨": "rain", "門": "gate", "貝": "shellfish / money",
    "車": "car / vehicle", "馬": "horse", "魚": "fish", "鳥": "bird", "隹": "old bird / turkey",
    "頁": "head / page", "大": "large / big", "小": "little / small", "山": "mountain", "川": "river",
    "工": "craft / work", "己": "self / snake", "巾": "towel / cloth", "干": "dry / clothesline",
    "弓": "bow", "戈": "halberd / fiesta", "斤": "axe", "方": "direction", "欠": "yawn / lack",
    "止": "stop / footprint", "歹": "bones / death", "殳": "missile / weapon", "毛": "fur",
    "水": "water", "爪": "claw", "牛": "cow", "犬": "dog", "白": "white", "皮": "skin / pelt",
    "皿": "dish / plate", "矢": "arrow / dart", "米": "rice", "肉": "meat", "自": "oneself / nose",
    "至": "climax / arrive", "舌": "tongue", "舟": "boat", "行": "going / line", "西": "west",
    "谷": "valley", "豆": "beans", "豕": "pig / sow", "身": "body", "辛": "spicy / bitter",
    "里": "village / ri", "長": "long", "青": "blue / green", "非": "un- / not", "面": "face / mask",
    "音": "sound", "首": "neck / head", "高": "tall", "鬼": "ghost / demon", "十": "ten / needle",
    "八": "eight", "二": "two", "入": "enter", "卜": "divining rod / magic wand", "夕": "evening",
    "寸": "glue / measurement", "幺": "cocoon / short thread", "文": "sentence / pattern",
    "斗": "Big Dipper / measure", "比": "compare", "氏": "family name", "玄": "mysterious",
    "生": "life / birth", "用": "use", "冫": "ice", "ヰ": "well", "五": "five", "吾": "I (literary)",
    "亡": "deceased", "并": "puzzle", "井": "well", "无": "nothing", "瓦": "tile", "甘": "sweet",
    "疋": "zoo / roll of cloth", "癶": "teepee / outspread legs", "老": "old man", "耂": "old man",
    "而": "rake / and yet", "臣": "retainer", "色": "color", "虍": "tiger", "血": "blood",
    "角": "horn / angle", "赤": "red", "辰": "sign of the dragon", "隶": "slave / reach",
    "革": "leather", "韋": "tanned leather", "風": "wind", "飛": "fly", "香": "incense / fragrance",
    "骨": "bone / skeleton", "髟": "long hair", "鬲": "tripod", "黄": "yellow", "黒": "black",
    "鼻": "nose", "齒": "tooth", "歯": "tooth", "龠": "flute", "亀": "turtle", "竜": "dragon",
}

# KRADFILE stand-in characters -> the radical they represent
STAND_INS = {"化": "亻", "汁": "氵", "扎": "扌", "艾": "艹", "忙": "忄", "込": "辶", "阡": "阝",
             "邦": "阝", "犯": "犭", "礼": "礻", "初": "衤", "尚": "⺌", "杰": "灬", "刈": "刂",
             "買": "罒", "个": "𠆢"}


@dataclass
class KanjiInfo:
    char: str
    keyword: str = ""            # Heisig / RTK keyword when known
    meanings: list[str] = field(default_factory=list)
    on: list[str] = field(default_factory=list)
    kun: list[str] = field(default_factory=list)
    strokes: int | None = None
    grade: int | None = None
    jlpt: int | None = None
    parts: list[tuple[str, str]] = field(default_factory=list)  # (component, meaning)
    part_colors: list[str] = field(default_factory=list)        # same order as parts
    part_positions: list[str] = field(default_factory=list)     # KanjiVG position words
    origin: str = ""             # why the parts make this character (Wiktionary glyph origin)
    origin_kind: str = ""        # e.g. "sound + meaning"
    svg: str = ""                # KanjiVG drawing with each part colored
    image_path: str = ""         # rendered PNG (made on the UI thread)
    story: str = ""              # ≤3-sentence mnemonic
    story_is_ai: bool = False


def is_kanji(c: str) -> bool:
    return ("㐀" <= c <= "鿿" or "豈" <= c <= "﫿"
            or "\U00020000" <= c <= "\U0003134f" or c in "々〆")


# kind of character formation -> (short label, one-line explanation)
ORIGIN_KINDS = [
    ("phono-semantic compound", "sound + meaning", "one part gives the meaning, the other the sound"),
    ("ideogrammatic compound", "meanings combined", "the parts' meanings add up to the idea"),
    ("compound ideogram", "meanings combined", "the parts' meanings add up to the idea"),
    ("pictogram", "picture", "it began as a drawing of the thing"),
    ("simple ideogram", "symbol", "an abstract sign for the idea"),
    ("ideogram", "symbol", "an abstract sign for the idea"),
    ("shinjitai", "simplified form", "a simplified Japanese form of an older character"),
    ("simplified from", "simplified form", "a simplified form of an older character"),
    ("variant of", "variant", "a variant of another character"),
]

PART_COLORS = ["#e8556d", "#3b8fe8", "#2fb383", "#f0a030", "#a46ee0", "#d65db1"]
OTHER_COLOR = "#9aa0a6"
KVG = "http://kanjivg.tagaini.net"
SVG = "http://www.w3.org/2000/svg"
POSITION_WORDS = {
    "left": "on the left", "right": "on the right", "top": "on top", "bottom": "at the bottom",
    "tare": "draped over the top-left", "tarec": "inside", "nyo": "sweeping under the bottom-left",
    "nyoc": "inside", "kamae": "around the outside", "kamaec": "inside", "kamae1": "around",
    "kamae2": "around",
}


def clean_origin_html(h: str) -> str:
    """Wiktionary 'Glyph origin' section HTML -> short plain text (≤2 sentences)."""
    h = re.sub(r"(?is)<(style|script|table|sup|h[1-6])\b.*?</\1>", " ", h)
    h = re.sub(r"(?is)<div[^>]*(?:mw-collapsible|thumb|gallery|NavFrame)[^>]*>.*?</div>", " ", h)
    h = re.sub(r"(?is)<ol class=\"references\".*?</ol>", " ", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"\[\s*edit\s*\]|\[\d+\]", " ", t)
    t = re.sub(r"\([^()]*\b(?:OC|MC|Baxter|Zhengzhang)\b[^()]*\)", "", t)
    t = re.sub(r"\(\s*[\u3000-\u30ff\u3400-\u9fff／/,，、\s]*\)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.;:)])", r"\1", t).replace("( ", "(")
    t = " ".join(split_sentences(t)[:2])
    if len(t) > 300:
        t = t[:297].rsplit(" ", 1)[0] + "…"
    return t


def split_sentences(t: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x]


def origin_kind(origin: str) -> tuple[str, str]:
    low = origin.lower()
    for key, short, expl in ORIGIN_KINDS:
        if key in low:
            return short, expl
    return "", ""


def layout_sentence(k: "KanjiInfo") -> str:
    """'cliff (厂) draped over the top-left, grove (林) inside and day (日) at the bottom → calendar.'"""
    if not k.parts:
        return ""
    items = []
    for i, (p, m) in enumerate(k.parts):
        pos = POSITION_WORDS.get(k.part_positions[i], "") if i < len(k.part_positions) else ""
        items.append(" ".join(x for x in (f"{m or 'part'} ({p})", pos) if x))
    body = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    key = k.keyword or (k.meanings[0] if k.meanings else "")
    return f"{body[0].upper()}{body[1:]} → {key}."


def template_story(k: "KanjiInfo") -> str:
    """Fallback without a story writer: the layout, plus the origin when it explains the meaning."""
    sentences = []
    lay = layout_sentence(k)
    if lay:
        sentences.append(lay)
    kind = origin_kind(k.origin)[0] if k.origin else ""
    if kind in ("meanings combined", "picture", "symbol"):
        # e.g. "Ideogrammatic compound: 亻 (“person”) + 木 (“tree”) – a person resting against a tree."
        orig = split_sentences(re.sub(r"^[^:]*compound[^:]*:\s*|^(?:Pictogram|Ideogram)\s*[–:-]\s*", "", k.origin))
        sentences += orig[:2]
    return " ".join(sentences[:3])


def template_word_story(word: str, meaning: str, infos: list["KanjiInfo"]) -> str:
    if len(infos) < 2:
        return ""
    parts = " + ".join(f"{k.char} {k.keyword or (k.meanings[0] if k.meanings else '')}".strip() for k in infos)
    return f"{parts} → {word}" + (f": {meaning}." if meaning else ".")


def cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "jpshot"
    d.mkdir(parents=True, exist_ok=True)
    return d


class KanjiDB:
    """Thread-unsafe by design: call it only from the dictionary's single worker thread."""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._krad: dict[str, list[str]] | None = None
        self._krad_failed = False
        self._info: dict[str, KanjiInfo] = {}
        self._api_cache_path = cache_dir() / "kanjiapi.json"
        self._api_cache: dict[str, dict] = {}
        try:
            if self._api_cache_path.exists():
                self._api_cache = json.loads(self._api_cache_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self._api_cache = {}
        self._jam = None
        self._origin_path = cache_dir() / "origins2.json"
        self._story_path = cache_dir() / "stories.json"
        try:
            self._stories: dict[str, str] = json.loads(self._story_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self._stories = {}
        self.provider = "auto"        # auto | anthropic | ollama | none
        self.api_key = ""
        self.story_model = "claude-haiku-5-5"
        self.ollama_url = "http://127.0.0.1:11434"
        self.ollama_model = "qwen2.5:7b"
        self._ollama_ok: tuple[float, bool] | None = None
        try:
            self._origins: dict[str, str] = json.loads(self._origin_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self._origins = {}

    # -- glyph origin (why the parts fit) ------------------------------------
    def _origin(self, ch: str) -> str:
        if ch in self._origins:
            return self._origins[ch]
        api = "https://en.wiktionary.org/w/api.php"
        text = ""
        try:
            sess = self._session_factory()
            r = sess.get(api, params={"action": "parse", "page": ch, "prop": "sections",
                                      "format": "json", "formatversion": "2"}, timeout=8)
            secs = r.json().get("parse", {}).get("sections", [])
            idx = next((s["index"] for s in secs if s.get("line", "").strip().lower() == "glyph origin"), None)
            if idx is not None:
                r = sess.get(api, params={"action": "parse", "page": ch, "section": idx, "prop": "text",
                                          "format": "json", "formatversion": "2",
                                          "disableeditsection": "1"}, timeout=8)
                text = clean_origin_html(r.json().get("parse", {}).get("text", ""))
            log.debug("Glyph origin %s: %s", ch, text or "(none)")
        except Exception as e:  # noqa: BLE001
            log.warning("Wiktionary glyph origin for %s failed: %s", ch, e)
            return ""   # don't cache failures
        self._origins[ch] = text
        try:
            self._origin_path.write_text(json.dumps(self._origins, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return text

    # -- KanjiVG: components with positions, colored drawing -------------------
    def _kanjivg(self, ch: str) -> str | None:
        d = cache_dir() / "kanjivg"
        d.mkdir(exist_ok=True)
        name = f"{ord(ch):05x}.svg"
        path = d / name
        missing = d / (name + ".missing")
        if path.exists() and path.stat().st_size:
            return path.read_text(encoding="utf-8")
        if missing.exists() and time.time() - missing.stat().st_mtime < 7 * 86400:
            return None
        urls = [f"https://raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/{name}",
                f"https://cdn.jsdelivr.net/gh/KanjiVG/kanjivg@master/kanji/{name}"]
        not_found = 0
        for url in urls:
            try:
                r = self._session_factory().get(url, timeout=10)
                if r.status_code == 404:
                    not_found += 1
                    log.info("KanjiVG has no drawing for %s (%s)", ch, url)
                    continue
                r.raise_for_status()
                text = r.content.decode("utf-8")
                path.write_text(text, encoding="utf-8")
                log.info("KanjiVG drawing for %s downloaded from %s", ch, url.split("/")[2])
                return text
            except Exception as e:  # noqa: BLE001
                log.warning("KanjiVG download for %s from %s failed: %s", ch, url.split("/")[2], e)
        if not_found == len(urls):
            missing.write_text("", encoding="utf-8")
        return None

    @staticmethod
    def _vg_split(svg_text: str, ch: str):
        """Returns (parts [(element, position)], colored svg text) or None."""
        ET.register_namespace("", SVG)
        ET.register_namespace("kvg", KVG)
        svg_text = re.sub(r"(?s)<!DOCTYPE.*?\]>", "", svg_text)
        if "xmlns:kvg" not in svg_text.split("<svg", 1)[-1].split(">", 1)[0]:
            svg_text = svg_text.replace("<svg ", f'<svg xmlns:kvg="{KVG}" ', 1)
        root = ET.fromstring(svg_text)
        el_attr, pos_attr = f"{{{KVG}}}element", f"{{{KVG}}}position"
        # remove the stroke-number labels
        for parent in root.iter():
            for child in list(parent):
                if child.get("id", "").startswith("kvg:StrokeNumbers"):
                    parent.remove(child)
        top = next((g for g in root.iter(f"{{{SVG}}}g") if g.get(el_attr) == ch), None)
        if top is None:
            return None
        parts: dict[str, dict] = {}
        order: list[str] = []
        loose: list = []

        def walk(g, inherited_pos=""):
            for child in g:
                if child.tag == f"{{{SVG}}}g":
                    el = child.get(el_attr)
                    pos = child.get(pos_attr) or inherited_pos
                    if el and el != ch:
                        if el not in parts:
                            parts[el] = {"pos": pos, "paths": []}
                            order.append(el)
                        parts[el]["paths"] += list(child.iter(f"{{{SVG}}}path"))
                    else:
                        walk(child, pos)
                elif child.tag == f"{{{SVG}}}path":
                    loose.append(child)

        walk(top)
        for i, el in enumerate(order):
            color = PART_COLORS[i % len(PART_COLORS)]
            for path in parts[el]["paths"]:
                path.set("style", f"stroke:{color}")
        for path in loose:
            path.set("style", f"stroke:{OTHER_COLOR if order else PART_COLORS[0]}")
        for g in root.iter(f"{{{SVG}}}g"):
            st = g.get("style", "")
            if "stroke-width" in st:
                g.set("style", re.sub(r"stroke-width:[\d.]+", "stroke-width:4", st))
        return [(el, parts[el]["pos"]) for el in order], ET.tostring(root, encoding="unicode")

    # -- story writer (LLM) -------------------------------------------------------
    def _active_provider(self) -> str:
        if self.provider in ("anthropic", "ollama", "none"):
            if self.provider == "anthropic" and not self._key():
                return "none"
            return self.provider
        if self._key():
            return "anthropic"
        return "ollama" if self._ollama_running() else "none"

    def has_writer(self) -> bool:
        return self._active_provider() != "none"

    def _key(self) -> str:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def _ollama_running(self) -> bool:
        if self._ollama_ok and time.time() - self._ollama_ok[0] < 60:
            return self._ollama_ok[1]
        try:
            ok = self._session_factory().get(f"{self.ollama_url}/api/tags", timeout=0.8).status_code == 200
        except Exception:  # noqa: BLE001
            ok = False
        self._ollama_ok = (time.time(), ok)
        return ok

    def _model_id(self, provider: str) -> str:
        return self.story_model if provider == "anthropic" else self.ollama_model

    def _llm(self, prompt: str) -> str:
        provider = self._active_provider()
        sess = self._session_factory()
        if provider == "anthropic":
            r = sess.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": self._key(), "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": self.story_model, "max_tokens": 260,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=40)
            if r.status_code != 200:
                raise RuntimeError(f"Anthropic API HTTP {r.status_code}: {r.text[:200]}")
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        elif provider == "ollama":
            r = sess.post(f"{self.ollama_url}/api/chat",
                          json={"model": self.ollama_model, "stream": False,
                                "messages": [{"role": "user", "content": prompt}],
                                "options": {"temperature": 0.7}}, timeout=120)
            if r.status_code != 200:
                raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]} "
                                   f"(did you run `ollama pull {self.ollama_model}`?)")
            text = r.json().get("message", {}).get("content", "")
        else:
            return ""
        text = re.sub(r"[*_#`]+", "", re.sub(r"\s+", " ", text)).strip().strip('"')
        return " ".join(split_sentences(text)[:3])

    def _cached_llm(self, cache_key: str, prompt: str, what: str) -> str:
        provider = self._active_provider()
        if provider == "none":
            return ""
        key = f"{cache_key}|{provider}:{self._model_id(provider)}"
        if key in self._stories:
            return self._stories[key]
        try:
            text = self._llm(prompt)
        except Exception as e:  # noqa: BLE001
            log.warning("Story for %s failed: %s", what, e)
            return ""
        if text:
            log.info("Story for %s (%s): %s", what, provider, text)
            self._stories[key] = text
            try:
                self._story_path.write_text(json.dumps(self._stories, ensure_ascii=False), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        return text

    def story(self, k: KanjiInfo) -> str:
        parts = "; ".join(
            f"{p} = '{m or '?'}'" + (f", {POSITION_WORDS[k.part_positions[i]]}"
                                     if i < len(k.part_positions) and k.part_positions[i] in POSITION_WORDS else "")
            for i, (p, m) in enumerate(k.parts)) or "no separate parts (it is a basic picture/symbol)"
        keyword = k.keyword or (k.meanings[0] if k.meanings else "?")
        prompt = (
            f"You help an English speaker remember the kanji {k.char} "
            f"(keyword: \"{keyword}\"; meanings: {', '.join(k.meanings[:5]) or keyword}).\n"
            f"Its parts: {parts}.\n"
            f"Real origin (may be useful): {k.origin or 'unknown'}\n\n"
            "In AT MOST 3 short sentences, explain WHY these parts add up to this meaning, as a vivid, "
            "logical picture or mini-story in the style of Remembering the Kanji, so the meaning feels "
            "obvious and sticks. If the real origin gives a memorable reason, build on it; if a part is only "
            "there for its sound, say so in a few words and build the picture from the other part. Refer to "
            "each part by its meaning with the character in parentheses. Do not name the formation type, do "
            "not list readings, no preamble, no markdown."
        )
        return self._cached_llm(f"kanji|{k.char}", prompt, k.char)

    def word_story(self, word: str, reading: str, meaning: str, infos: list[KanjiInfo]) -> str:
        if len(infos) < 2:
            return ""
        kanji = "; ".join(f"{k.char} = '{k.keyword or (k.meanings[0] if k.meanings else '?')}' "
                          f"(also: {', '.join(k.meanings[:4])})" for k in infos)
        prompt = (
            f"Explain to an English-speaking Japanese learner why the word {word}"
            f"{f' ({reading})' if reading else ''} means \"{meaning or '?'}\".\n"
            f"Its kanji: {kanji}.\n\n"
            "In AT MOST 3 short sentences, show how the kanji meanings combine into the word's meaning in a "
            "way that sticks: logical first, vivid if it helps. Mention each kanji with its meaning. "
            "Plain text only, no preamble, no markdown."
        )
        return self._cached_llm(f"word|{word}", prompt, word)

    # -- components -------------------------------------------------------
    def _load_krad(self) -> dict[str, list[str]]:
        if self._krad is not None:
            return self._krad
        if self._krad_failed:
            return {}
        path = cache_dir() / "krad.json"
        if path.exists():
            try:
                self._krad = json.loads(path.read_text(encoding="utf-8"))
                log.info("Loaded kanji components (%d kanji) from %s", len(self._krad), path)
                return self._krad
            except Exception:  # noqa: BLE001
                log.warning("Corrupt %s; downloading again", path)
        krad: dict[str, list[str]] = {}
        sess = self._session_factory()
        for urls in (KRAD_URLS, KRAD2_URLS):
            for url in urls:
                try:
                    log.info("Downloading kanji component data from %s …", url)
                    r = sess.get(url, timeout=20)
                    r.raise_for_status()
                    text = gzip.decompress(r.content).decode("euc_jp", errors="replace")
                    for line in text.splitlines():
                        if not line or line.startswith("#") or " : " not in line:
                            continue
                        k, comps = line.split(" : ", 1)
                        krad.setdefault(k.strip(), comps.split())
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning("Could not get %s: %s", url, e)
        if not krad:
            log.error("Kanji component data unavailable (no internet?); breakdown will show meanings only")
            self._krad_failed = True
            return {}
        path.write_text(json.dumps(krad, ensure_ascii=False), encoding="utf-8")
        log.info("Saved kanji components for %d kanji to %s", len(krad), path)
        self._krad = krad
        return krad

    def _parts(self, ch: str) -> list[str]:
        krad = self._load_krad()
        comps = [c for c in krad.get(ch, []) if c != ch]
        # KRADFILE lists every sub-part; drop parts already contained in another listed part
        # (語: 口 五 言 -> 言 五), which is closer to how RTK splits a kanji.
        keep = []
        for c in comps:
            inside_other = any(c != o and c in krad.get(o, []) for o in comps)
            if not inside_other:
                keep.append(c)
        return keep

    # -- meanings -------------------------------------------------------------
    def _api(self, ch: str) -> dict | None:
        if ch in self._api_cache:
            return self._api_cache[ch]
        try:
            r = self._session_factory().get(f"https://kanjiapi.dev/v1/kanji/{ch}", timeout=8)
            log.debug("kanjiapi.dev %s -> HTTP %s", ch, r.status_code)
            data = r.json() if r.status_code == 200 else None
        except Exception as e:  # noqa: BLE001
            log.warning("kanjiapi.dev lookup for %s failed: %s", ch, e)
            return None
        self._api_cache[ch] = data
        try:
            self._api_cache_path.write_text(json.dumps(self._api_cache, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return data

    def _jamdict_info(self, ch: str) -> dict | None:
        try:
            if self._jam is None:
                from jamdict import Jamdict

                self._jam = Jamdict()
            res = self._jam.lookup(ch)
            if not res.chars:
                return None
            c = res.chars[0]
            meanings, on, kun = [], [], []
            for g in c.rm_groups:
                meanings += [m.value for m in g.meanings if getattr(m, "m_lang", "") in ("", "en")]
                on += [r.value for r in g.readings if r.r_type == "ja_on"]
                kun += [r.value for r in g.readings if r.r_type == "ja_kun"]
            return {"meanings": meanings, "on_readings": on, "kun_readings": kun,
                    "stroke_count": c.stroke_count, "grade": c.grade, "jlpt": c.jlpt}
        except Exception:  # noqa: BLE001
            return None

    def _meaning_of_part(self, part: str) -> str:
        if part in RADICALS:
            return RADICALS[part]
        d = self._api(part) if is_kanji(part) else None
        if d:
            return d.get("heisig_en") or ", ".join(d.get("meanings", [])[:2])
        return ""

    def info(self, ch: str) -> KanjiInfo:
        if ch in self._info:
            return self._info[ch]
        k = KanjiInfo(char=ch)
        d = self._api(ch) or self._jamdict_info(ch)
        if d:
            k.keyword = d.get("heisig_en") or ""
            k.meanings = list(d.get("meanings") or [])[:5]
            k.on = list(d.get("on_readings") or [])[:4]
            k.kun = list(d.get("kun_readings") or [])[:4]
            k.strokes = d.get("stroke_count")
            k.grade = d.get("grade")
            k.jlpt = d.get("jlpt")
        split = None
        svg_text = self._kanjivg(ch)
        if svg_text:
            try:
                split = self._vg_split(svg_text, ch)
            except Exception:  # noqa: BLE001
                log.exception("Could not read KanjiVG data for %s", ch)
        if svg_text and not split:
            log.warning("KanjiVG drawing for %s could not be split into parts", ch)
        if split:
            vg_parts, k.svg = split
            log.info("Kanji %s parts (KanjiVG): %s", ch, " + ".join(el for el, _ in vg_parts) or "(single part)")
            k.parts = [(el, self._meaning_of_part(el)) for el, _pos in vg_parts]
            k.part_positions = [pos for _el, pos in vg_parts]
        else:
            k.parts = [(STAND_INS.get(p, p), self._meaning_of_part(p)) for p in self._parts(ch)]
            k.part_positions = ["" for _ in k.parts]
        k.part_colors = [PART_COLORS[i % len(PART_COLORS)] for i in range(len(k.parts))]
        k.origin = self._origin(ch)
        k.origin_kind = origin_kind(k.origin)[0]
        k.story = template_story(k)
        self._info[ch] = k
        log.debug("Kanji %s: keyword=%r meanings=%s parts=%s", ch, k.keyword, k.meanings, k.parts)
        return k

    def breakdown(self, word: str) -> list[KanjiInfo]:
        seen, out = set(), []
        for c in word:
            if is_kanji(c) and c not in "々〆" and c not in seen:
                seen.add(c)
                out.append(self.info(c))
        return out


def render_png(k: KanjiInfo, size: int = 110) -> str:
    """Render the colored KanjiVG drawing to a PNG for the popup (call on the UI thread)."""
    if not k.svg:
        return ""
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    d = cache_dir() / "kanji_png"
    d.mkdir(exist_ok=True)
    path = d / f"{ord(k.char):05x}-{size}.png"
    renderer = QSvgRenderer(QByteArray(k.svg.encode("utf-8")))
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()
    img.save(str(path))
    return str(path)


def to_html(infos: list[KanjiInfo], accent: str, word: str = "", word_story: str = "",
            show_hint: bool = False) -> str:
    if not infos:
        return ""
    from PySide6.QtCore import QUrl

    h = "<div style='margin-top:8px'><b>Kanji</b></div>"
    if word_story:
        h += (f"<div style='margin:2px 0 6px 0'><b>Why {html.escape(word)} means this:</b> "
              f"{html.escape(word_story)}</div>")
    for k in infos:
        key = k.keyword or (k.meanings[0] if k.meanings else "")
        if k.image_path:
            pic = f"<img src='{QUrl.fromLocalFile(k.image_path).toString()}' width='110' height='110'>"
        else:
            pic = f"<span style='font-size:40pt'>{html.escape(k.char)}</span>"
        info = f"<b style='color:{accent};font-size:13pt'>{html.escape(key)}</b>"
        tags = [t for t in (f"{k.strokes} strokes" if k.strokes else "",
                            f"JLPT N{k.jlpt}" if k.jlpt else "",
                            k.origin_kind) if t]
        if tags:
            info += f" <span style='color:gray;font-size:9pt'>{html.escape(' · '.join(tags))}</span>"
        if k.parts:
            pieces = " + ".join(
                f"<span style='color:{k.part_colors[i] if i < len(k.part_colors) else accent}'>"
                f"<b>{html.escape(p)}</b></span>" + (f" <i style='color:gray'>{html.escape(m)}</i>" if m else "")
                for i, (p, m) in enumerate(k.parts))
            info += f"<br>{pieces}"
        rd = []
        if k.on:
            rd.append("on " + "、".join(k.on[:3]))
        if k.kun:
            rd.append("kun " + "、".join(k.kun[:3]))
        if rd:
            info += f"<br><span style='color:gray'>{html.escape('  ·  '.join(rd))}</span>"
        h += (f"<table cellspacing='0' cellpadding='2' style='margin-top:4px'><tr>"
              f"<td valign='top'>{pic}</td><td valign='top'>{info}</td></tr></table>")
        if k.story:
            label = "Why" if k.story_is_ai else "Layout"
            h += f"<div style='margin:0 0 4px 4px'><b>{label}:</b> {html.escape(k.story)}</div>"
    if show_hint:
        h += ("<div style='color:gray;font-size:9pt;margin-top:4px'>For memorable explanations of why the "
              "parts mean this, set up a story writer in ⚙ Settings (free local Ollama, or an API key).</div>")
    return h
