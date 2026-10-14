"""Optional feature sets. The basics are always on; everything here is off until you enable it in
⚙ Settings → Selectable features, so the window only shows what you use."""
from __future__ import annotations

BASICS = ("Capture & OCR, the English / Japanese / Furigana / Hiragana / Rōmaji boxes, translation, "
          "read-aloud with speed control, the word popup (dictionary, reading, audio, English-word "
          "lookups), copy, dark mode")

# key, label, description
FEATURES = [
    ("image", "Screenshot panel", "Show the screenshot beside the text (zoom with the wheel, drag to move)"),
    ("selection", "Highlight to translate", "Translate just the part of a box you highlight"),
    ("grammar", "Grammar", "Color words by part of speech, list grammar points (〜わけではない…), "
                           "and explain each word's role in the popup"),
    ("pitch", "Pitch accent", "Color pitch per sound or per word, and draw the pitch in the popup"),
    ("difficulty", "Difficulty", "Rate each sentence (≈JLPT) and color words from easy to hard"),
    ("known", "Known words", "Track words you know (Anki sync, K to mark), highlight new words, spot i+1 sentences"),
    ("kanji", "Kanji breakdown", "Kanji drawn with colored parts, readings, words sharing the kanji, stroke order"),
    ("explanations", "Explanations", "Short written explanations of why kanji and words mean what they do "
                                     "(needs Ollama or an API key)"),
    ("examples", "Examples & forms", "Example sentences and conjugation tables in the popup"),
    ("ask", "Ask a tutor", "Chat about the sentence: structure, particles, nuance (needs Ollama or an API key)"),
    ("anki", "Anki mining", "⛏ Mine cards into Anki, including the JPShot card type and Hearing cards"),
    ("history", "History", "Keep every capture, search them, see words you keep running into"),
    ("shadow", "Shadowing", "Record yourself and compare with the voice, including a pitch graph"),
]
KEYS = [k for k, _l, _d in FEATURES]


def enabled(cfg, key: str) -> bool:
    return key in (cfg.features or [])
