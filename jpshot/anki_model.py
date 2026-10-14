"""The 'JPShot Sentence' Anki note type, created/updated through AnkiConnect.

Two card types, generated per note depending on flags:
  Reading — front: image + Japanese sentence (optionally in a random font and size, 🔀 to reshuffle)
            back:  image, sentence with furigana, English, word, audio (plays automatically)
  Hearing — front: image + audio (a random voice)
            back:  image, sentence with furigana, English, word (no audio, so it doesn't replay)
"""
from __future__ import annotations

import logging

from . import anki

log = logging.getLogger("jpshot.anki")

MODEL_NAME = "JPShot Sentence"
FIELDS = ["Sentence", "Furigana", "English", "Image", "Audio", "HearingAudio", "Word", "WordReading",
          "WordMeaning", "Notes", "Reading", "Hearing", "RandomFont", "Voice"]

# Japanese fonts to pick from; only the ones installed on the reviewing device are used.
FONTS = [
    "Noto Sans CJK JP", "Noto Serif CJK JP", "Noto Sans JP", "Noto Serif JP", "IPAexGothic",
    "IPAexMincho", "IPAGothic", "IPAMincho", "IPAPGothic", "IPAPMincho", "TakaoPGothic", "TakaoPMincho",
    "VL PGothic", "M PLUS 1p", "M PLUS Rounded 1c", "Kosugi Maru", "Sawarabi Mincho", "Sawarabi Gothic",
    "Zen Maru Gothic", "Zen Old Mincho", "Zen Kurenaido", "Klee One", "Kiwi Maru", "Shippori Mincho",
    "Yomogi", "Hachi Maru Pop", "Yusei Magic", "Dela Gothic One", "Reggae One", "RocknRoll One",
    "Source Han Sans JP", "Source Han Serif JP", "Sarasa Gothic J", "HackGen", "Ume Mincho",
    "Yu Gothic", "Yu Mincho", "Meiryo", "MS Gothic", "MS Mincho", "BIZ UDGothic", "BIZ UDMincho",
    "UD Digi Kyokasho N-R", "HGSeikaishotaiPRO", "HGMaruGothicMPRO", "Hiragino Sans",
    "Hiragino Mincho ProN", "Hiragino Maru Gothic ProN", "Klee", "Toppan Bunkyu Mincho",
    "Tsukushi A Round Gothic", "Kyokasho ProN", "YuKyokasho",
]

_FONTS_JS = ",".join(f'"{f}"' for f in FONTS)

SHUFFLE = """
<button class="jps-shuffle" onclick="jpshotShuffle()" title="Another font and size">🔀</button>
<script>
(function () {
  var fonts = [%FONTS%];
  function installed(f) {
    var c = document.createElement("canvas").getContext("2d"), t = "日本語の文字テスト";
    return ["monospace", "serif"].some(function (base) {
      c.font = "40px " + base; var w0 = c.measureText(t).width;
      c.font = "40px '" + f + "', " + base; return c.measureText(t).width !== w0;
    });
  }
  var avail = window.__jpsFonts || (window.__jpsFonts = fonts.filter(installed));
  if (!avail.length) avail = ["serif", "sans-serif"];
  window.jpshotShuffle = function () {
    var el = document.getElementById("jps-sentence");
    if (!el) return;
    var f = avail[Math.floor(Math.random() * avail.length)];
    el.style.fontFamily = (f === "serif" || f === "sans-serif") ? f : "'" + f + "', sans-serif";
    el.style.fontSize = (1.3 + Math.random() * 1.2).toFixed(2) + "em";   /* ~70%–140% of normal */
    el.style.letterSpacing = (Math.random() * 0.12 - 0.02).toFixed(2) + "em";
  };
  jpshotShuffle();
})();
</script>
""".replace("%FONTS%", _FONTS_JS)

WORD = """{{#Word}}<div class="jps-word"><span class="jps-wordjp">{{furigana:Word}}</span>
{{#WordMeaning}}<div class="jps-wordmeaning">{{WordMeaning}}</div>{{/WordMeaning}}</div>{{/Word}}"""

ANSWER = """<div class="jps-img">{{Image}}</div>
<div class="jps-furigana">{{furigana:Furigana}}</div>
<div class="jps-english">{{English}}</div>
""" + WORD + """
{{#Notes}}<div class="jps-notes">{{Notes}}</div>{{/Notes}}"""

READING_FRONT = """{{#Reading}}
<div class="jps-img">{{Image}}</div>
<div id="jps-sentence" class="jps-sentence">{{Sentence}}</div>
{{#RandomFont}}""" + SHUFFLE + """{{/RandomFont}}
{{/Reading}}"""

READING_BACK = """{{#Reading}}
""" + ANSWER + """
<div class="jps-audio">{{Audio}}</div>
{{/Reading}}"""

HEARING_FRONT = """{{#Hearing}}
<div class="jps-img">{{Image}}</div>
<div class="jps-listen">🎧 Listen{{#Voice}}<div class="jps-voice">{{Voice}}</div>{{/Voice}}</div>
{{HearingAudio}}
{{/Hearing}}"""

HEARING_BACK = """{{#Hearing}}
""" + ANSWER + """
{{#Voice}}<div class="jps-voice">voice: {{Voice}}</div>{{/Voice}}
{{/Hearing}}"""

CSS = """
.card { font-family: "Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
        font-size: 20px; text-align: center; color: #1d1d1f; background: #fafafa; line-height: 1.6; }
.card.nightMode, .nightMode .card { color: #e7e7ea; background: #1f2023; }
.jps-img img { max-width: 100%; max-height: 42vh; border-radius: 8px; box-shadow: 0 1px 6px rgba(0,0,0,.25); }
.jps-sentence { font-size: 1.8em; margin: .6em .4em; }
.jps-furigana { font-size: 1.6em; margin: .5em .4em .2em; line-height: 2.1; }
.jps-furigana rt, .jps-wordjp rt { font-size: .5em; color: #e8556d; }
.jps-english { font-size: 1.05em; color: #555; margin: .3em .6em .8em; }
.nightMode .jps-english { color: #b9bac0; }
.jps-word { display: inline-block; margin-top: .4em; padding: .4em .8em; border-radius: 8px;
            background: rgba(232,85,109,.08); }
.jps-wordjp { font-size: 1.3em; }
.jps-wordmeaning { font-size: .85em; color: #666; white-space: pre-line; text-align: left; }
.nightMode .jps-wordmeaning { color: #aaa; }
.jps-notes { margin-top: .8em; font-size: .85em; color: #777; white-space: pre-line; }
.jps-listen { font-size: 1.6em; margin: .8em; }
.jps-voice { font-size: .55em; color: #999; }
.jps-shuffle { border: none; background: transparent; font-size: 1.1em; cursor: pointer; opacity: .6; }
.jps-shuffle:hover { opacity: 1; }
"""

TEMPLATES = {
    "Reading": {"Front": READING_FRONT, "Back": READING_BACK},
    "Hearing": {"Front": HEARING_FRONT, "Back": HEARING_BACK},
}


def ensure_model(url: str) -> str:
    """Create the note type, or bring an existing one up to date. Returns its name."""
    models = anki.invoke(url, "modelNames")
    if MODEL_NAME not in models:
        anki.invoke(url, "createModel", modelName=MODEL_NAME, inOrderFields=FIELDS, css=CSS, isCloze=False,
                    cardTemplates=[{"Name": n, "Front": t["Front"], "Back": t["Back"]}
                                   for n, t in TEMPLATES.items()])
        log.info("Created Anki note type %r", MODEL_NAME)
        return MODEL_NAME
    have = anki.invoke(url, "modelFieldNames", modelName=MODEL_NAME)
    for i, f in enumerate(FIELDS):
        if f not in have:
            try:
                anki.invoke(url, "modelFieldAdd", modelName=MODEL_NAME, fieldName=f, index=i)
                log.info("Added field %s to %r", f, MODEL_NAME)
            except anki.AnkiError as e:
                log.warning("Could not add field %s (old AnkiConnect?): %s", f, e)
    try:
        anki.invoke(url, "updateModelTemplates", model={"name": MODEL_NAME, "templates": TEMPLATES})
        anki.invoke(url, "updateModelStyling", model={"name": MODEL_NAME, "css": CSS})
    except anki.AnkiError as e:
        log.warning("Could not update %r templates: %s", MODEL_NAME, e)
    return MODEL_NAME
