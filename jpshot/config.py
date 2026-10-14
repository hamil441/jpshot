"""Persistent settings stored as JSON in the user's config directory."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "jpshot"
    d.mkdir(parents=True, exist_ok=True)
    return d


ALL_SECTIONS = ("english", "japanese", "furigana", "hiragana", "romaji")


@dataclass
class Config:
    # Global hotkey (pynput syntax). Set to "" to disable and bind
    # `python -m jpshot capture` in your OS shortcut settings instead.
    hotkey: str = "<ctrl>+<alt>+j"

    # OCR
    tesseract_cmd: str = ""          # full path if tesseract isn't on PATH
    ocr_languages: str = "jpn+eng"
    ocr_min_confidence: int = 55     # 0-100; raise if you get garbage text
    ocr_min_chars: int = 2           # fewer meaningful chars => "nothing detected"

    # Translation: "google" (tries Google, then MyMemory, then offline Argos),
    # "mymemory" (try MyMemory first) or "argos" (offline only)
    translator: str = "google"

    # Text-to-speech: "edge" (natural neural voices, online) or "gtts"
    tts_engine: str = "edge"
    tts_voice: str = "ja-JP-NanamiNeural"   # or ja-JP-KeitaNeural
    tts_speed: float = 1.0
    voice: str = ""                  # voice id, e.g. edge:ja-JP-NanamiNeural or voicevox:3
    hearing_voices: list = field(default_factory=list)   # voice ids for Hearing cards; [] = all

    # Dictionary: "auto" (offline JMdict via jamdict if installed, else jisho.org),
    # "jamdict" or "jisho"
    dictionary: str = "auto"

    # Look & layout
    theme: str = "system"            # system | light | dark
    grammar_mode: bool = False       # color words by part of speech
    show_image: bool = True          # screenshot panel beside the text
    lookup_key: str = "shift"        # hold this over a word for the popup: shift | ctrl | alt | meta
    japanese_font_size: int = 20
    english_font_size: int = 13
    # Which rows the result window shows, in order
    sections: list = field(default_factory=lambda: ["japanese"])

    # Optional: Anthropic API key for short RTK-style kanji stories (also read from ANTHROPIC_API_KEY)
    anthropic_api_key: str = ""
    story_model: str = "claude-haiku-5-5"

    # Anki (via the AnkiConnect add-on)
    anki_url: str = "http://127.0.0.1:8765"
    anki_deck: str = ""
    anki_model: str = ""
    anki_tags: str = "jpshot"
    anki_field_map: dict = field(default_factory=dict)   # note type -> {field name: content key}
    anki_audio: bool = True
    anki_reading: bool = True        # JPShot card type: make a Reading card
    anki_hearing: bool = False       # ... and/or a Hearing card
    anki_random_font: bool = True

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        p = cls.path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                for k, v in data.items():
                    if k in known:
                        setattr(cfg, k, v)
            except Exception as e:  # corrupt file: keep defaults
                print(f"[jpshot] could not read config: {e}", file=sys.stderr)
        else:
            cfg.save()
        if not cfg.voice:  # migrate from tts_engine/tts_voice
            cfg.voice = "gtts:ja" if cfg.tts_engine == "gtts" else f"edge:{cfg.tts_voice or 'ja-JP-NanamiNeural'}"
        return cfg

    def save(self) -> None:
        try:
            self.path().write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[jpshot] could not save config: {e}", file=sys.stderr)
