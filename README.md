# JPShot

A Flameshot-style screenshot tool for learning Japanese. Press the hotkey, drag around any text on screen, and if JPShot finds English or Japanese text it opens a study window with every version of the text stacked together:

- **English**, **日本語** (original), **Furigana** (readings drawn above the kanji), **ひらがな** and **Rōmaji** — click one in the row at the top to show just that box, or Ctrl+click to show several at once. Everything is selectable and copyable.
- **Select to translate** — highlight part of any row and just that part is translated in a bar at the top.
- **Dictionary popup** — hold **Shift** and hover a Japanese word: reading, rōmaji, dictionary form, meanings, its grammatical role, and a **kanji breakdown** in the spirit of *Remembering the Kanji*: the kanji drawn with each part in its own color, the RTK keyword, the parts and their meanings in matching colors, readings, and a short (≤3 sentence) explanation of how the parts make the meaning.
- **Word coloring** (one at a time): **Grammar** colors words by part of speech; **Pitch** by pitch accent (blue heiban, red atamadaka, orange nakadaka, green odaka); **Difficulty** from easy (green) to hard (red). Hold Shift over a word for its explanation, including its pitch drawn over the reading (high sounds overlined, ꜜ where it drops).
- **Word audio** — 🔊 in the word popup (or press W) plays just that word; 🔊 in the selection bar plays what you highlighted.
- **Read in Japanese** — neural text-to-speech with a **speed slider** (0.5× – 2×) always visible at the bottom.
- **⛏ Mine** — make an Anki card from the capture: screenshot (plus more screenshots, image files or a pasted image), every version of the text, the word you looked up and its meaning, and the Japanese audio.
- **Screenshot panel** beside the text (🖼, Ctrl+I): scroll to zoom, drag to move, double-click to fit.
- **Voice library**: Microsoft and Google voices, plus every VOICEVOX / AivisSpeech voice when those free apps are running.
- **Difficulty rating** — each sentence gets an estimated level (≈JLPT N5–N1, ★–★★★★★) from its kanji, word frequency, grammar and length; hover it for the reasons. Saved on mined cards as a field and a `difficulty::N3`-style tag.
- **Copy image**, **dark mode** (☾/☀ button) and a **⚙ Settings** window.

If no text is detected, nothing happens.

Everything is logged to the terminal you start it from (add `--debug` for full detail).

## Selectable features

Out of the box JPShot shows only the basics: capture & OCR, the English / Japanese / Furigana / Hiragana / Rōmaji boxes, translation, read-aloud, the sentence difficulty rating, the word popup, copy and dark mode. Turn on what you want in **⚙ Settings → Selectable features**:

| Feature | What it adds |
|---|---|
| Screenshot panel | the capture beside the text; scroll to zoom, drag to move |
| Highlight to translate | translates just the part you highlight (🔊 reads it) |
| Grammar | part-of-speech coloring, grammar points like 〜わけではない (click to underline), word roles in the popup |
| Pitch accent | high/low per sound in the kana boxes, pattern colors per word, pitch drawn in the popup |
| Word difficulty | words colored easy → hard, and each word's ≈JLPT level in the popup |
| Known words | Anki sync of words you've reviewed (at start-up, when you switch it on, and every 30 min; works with Kaishi 1.5k, Core and most vocab decks — words written in kana match their kanji forms), **K** to mark known, new words highlighted, **i+1** badge, furigana only over kanji you don't know, duplicate warnings when mining |
| Kanji breakdown | kanji drawn with colored parts, readings, common words sharing the kanji, ✍ animated stroke order |
| Explanations | why each kanji's parts and each word's kanji mean what they do (Ollama or API key) |
| Examples & forms | example sentences (Tatoeba) and conjugation tables in the popup |
| Ask a tutor | ❓ Ask (Ctrl+E): chat about the sentence's structure, particles and nuance |
| Anki mining | ⛏ Mine (Ctrl+M), the JPShot card type, Reading/Hearing cards |
| History | 📜 (Ctrl+H, `jpshot history`): every capture, searchable, reopenable, plus "words you keep seeing" |
| Shadowing | 🎙 record yourself, compare with the voice, pitch-contour graph |

Turning a feature off also hides its settings and stops its background work. Right-click any Japanese word for **▶ Play from here** / **▶ Play this phrase**. The English box is editable: change it and click a Japanese box (or Ctrl+Enter) to re-translate.

## Install

**1. Python 3.9+**, then from this folder:

```bash
pip install -e .            # installs the `jpshot` command
# or: pip install -r requirements.txt   and run with  python -m jpshot
```

**2. Tesseract OCR with Japanese data**

| OS | Command |
|---|---|
| Windows | Install from https://github.com/UB-Mannheim/tesseract/wiki and tick **Japanese** under *Additional language data* during setup |
| macOS | `brew install tesseract tesseract-lang` |
| Ubuntu/Debian | `sudo apt install tesseract-ocr tesseract-ocr-jpn` |
| Fedora | `sudo dnf install tesseract tesseract-langpack-jpn` |
| Arch | `sudo pacman -S tesseract tesseract-data-jpn tesseract-data-eng` |

**3. Check everything works**

```bash
jpshot check
```

This tests Qt, Tesseract (with jpn + eng), the Japanese tokenizer, translation, the dictionary and TTS, and tells you exactly what's missing.

## Run

```bash
jpshot                 # start (tray icon + global hotkey), logs here; Ctrl+C to quit
jpshot --debug         # same, with verbose debug logs
jpshot capture         # take a capture now (sends it to the running instance, or starts one)
jpshot file shot.png   # open the result window for an existing image
jpshot ocr shot.png    # terminal only: prints OCR text, translation, furigana and hiragana
jpshot settings        # open the settings window
jpshot quit            # stop the running instance
```

Without installing, replace `jpshot` with `python -m jpshot`.

Default hotkey: **Ctrl+Alt+J**. Left-clicking the tray icon also starts a capture.

## Using it

| Where | Key / action | Does |
|---|---|---|
| Capture | drag | draw a box |
| Capture | drag the handles / drag inside | resize / move the box (drag outside to start over) |
| Capture | arrow keys (Shift = resize, Ctrl = ×10) | nudge the box |
| Capture | Enter or double-click | capture |
| Capture | Esc / right-click | cancel |
| Result | click a box name in the top row, or Alt+1 … Alt+5 | show only that box (English, 日本語, Furigana, ひらがな, Rōmaji) |
| Result | Ctrl+click a box name | show several boxes at once |
| Result | select text in any row | translate just that part |
| Result | Shift + hover a Japanese word (key changeable in Settings) | dictionary, grammar and kanji popup |
| Result | Shift + hover an English word | the Japanese word for it, with the same popup (plus alternatives) |
| Result | Grammar / Pitch / Difficulty (Alt+G / Alt+P / Alt+D) | color words by that scheme; click again to turn off |
| Result | W, or 🔊 in the popup | hear the word under the popup |
| Result | 🖼 or Ctrl+I | show/hide the screenshot panel (scroll = zoom, drag = move, double-click = fit) |
| Result | Esc | close popup, then the window |
| Result | Space | play / stop audio |
| Result | `[` / `]` | slower / faster speech |
| Result | Ctrl+Shift+C or *Copy image* | copy the screenshot |
| Result | ☾ / ☀ | dark / light mode |
| Result | ⚙ or Ctrl+, | settings |

The result window stays open while you take the next capture and simply updates; move it wherever you like and it stays there. Changing the speed while audio is playing restarts it at the new speed from about the same spot. Your choices are remembered.

In Pitch mode the ひらがな and Furigana rows show pitch per sound (orange = high, blue = low; the pitch drops where orange turns blue, and particles follow the word before), while the 日本語 and Rōmaji rows color whole words by pattern. Pitch accent comes from UniDic's accent data (Tokyo standard). For verbs and adjectives it's shown for the dictionary form, since conjugation can move the drop; treat it as a guide.

Grammar colors: blue = noun, red = verb, orange = adjective, purple = adverb, green = particle, pink = auxiliary (tense, politeness, negation…).

**Explanations.** The kanji part of the popup explains *why* each kanji's parts mean what they do, and for words with two or more kanji, *why those kanji together* make the word's meaning (e.g. 変 + 更 → 変更) — at most three sentences each, written once and saved. That needs a story writer, set in ⚙ Settings:

- **Ollama (free, runs on your computer):** `sudo pacman -S ollama`, `sudo systemctl enable --now ollama`, `ollama pull qwen2.5:7b`. JPShot finds it automatically. Larger models (e.g. `gemma3:12b`) write better explanations if your machine can run them.
- **Anthropic API:** paste an API key; the default model costs a fraction of a cent per explanation.

Without one, you get each kanji's part layout (and its origin when that explains the meaning).

The colored drawings use KanjiVG stroke data (CC BY-SA 3.0, downloaded per kanji). The first kanji breakdown downloads the KRADFILE component data (about 100 KB, EDRDG, CC BY-SA) into `~/.cache/jpshot/`; kanji meanings and RTK keywords come from kanjiapi.dev, and the "why" explanations from Wiktionary's glyph-origin notes; all are cached.

## Anki mining

1. In Anki: **Tools → Add-ons → Get Add-ons…**, enter **2055492159** (AnkiConnect), and restart Anki.
2. Keep Anki open while you use JPShot.
3. After a capture, click **⛏ Mine** (Ctrl+M). Choose a deck (or **+ New deck…** to create one) and note type, then choose what goes in each field. JPShot guesses from the field names (Sentence, Meaning, Picture, Audio…) and remembers your choices per note type.
4. Edit any text, add or remove images (📷 takes another screenshot without leaving the dialog), and press **Add card** (Ctrl+Enter).

Anki requires a card's **first field** to have something in it. For vocabulary note types that's usually the word: Shift-hover a word before mining, highlight it, or type it in the dialog's Word box and press **Look up** to fill its furigana, reading, meaning and part of speech. **Guess fields again** re-guesses the field choices for a note type.

### The JPShot card type

Press **Use JPShot card type** in the Mine dialog to create a ready-made *JPShot Sentence* note type in Anki (pressing it again updates it). Then choose per card:

- **Reading card** — front: the image and the Japanese sentence; back: the sentence with furigana, the English, the image, the looked-up word, and the audio, which plays automatically.
- **Random font and size** — the Japanese on the Reading front appears in a different installed Japanese font and size each review (🔀 on the card reshuffles), so you learn the characters, not one font. Installing more Japanese fonts gives more variety (Arch: `noto-fonts-cjk`, `otf-ipaexfont`, …).
- **Hearing card** — front: the image and the audio, spoken by a random voice from your Hearing-card voices; back: furigana and English (the audio doesn't replay).

Tick both to get both cards from one capture.

### More voices

The free Microsoft service has two Japanese voices (Nanami and Keita), plus Google's. For many more, install **VOICEVOX** (free; Arch: AUR package `voicevox`, or Docker `voicevox/voicevox_engine:cpu-latest`) and keep it running. JPShot finds its voices automatically, and also those of **AivisSpeech**. Pick your main voice and the pool for Hearing cards in ⚙ Settings. Check each VOICEVOX character's terms if you share cards publicly; the voice name is saved on Hearing cards.

Furigana is written in Anki's format (`食[た]べる`), so it shows above the kanji on cards that use `{{furigana:Field}}`. If you Shift-hover a word before mining, that word, its reading and its meaning are filled in too.

## Configuration

Use **⚙ Settings** in the window (or `jpshot settings`). Changes apply immediately, including the hotkey. Settings are stored in `config.json` (on Linux `~/.config/jpshot/`, Windows `%APPDATA%\jpshot\`, macOS `~/Library/Application Support/jpshot/`), which you can also edit by hand:

| Key | Default | Notes |
|---|---|---|
| `hotkey` | `<ctrl>+<alt>+j` | pynput syntax, e.g. `<shift>+<print_screen>`. `""` disables it |
| `tesseract_cmd` | `""` | full path if Tesseract isn't found automatically |
| `ocr_min_confidence` | `55` | raise it if you get garbage text, lower it if text is missed |
| `translator` | `google` | Google with automatic fallbacks; `mymemory`; or `argos` (offline) |
| `voice` | `edge:ja-JP-NanamiNeural` | voice id; pick from the list in Settings |
| `hearing_voices` | `[]` | voices for Hearing cards (empty = all) |
| `lookup_key` | `shift` | key held for the word popup: `shift`, `ctrl`, `alt`, `meta` |
| `show_image` | `true` | screenshot panel beside the text |
| `dictionary` | `auto` | offline JMdict if installed, else jisho.org; or force `jamdict` / `jisho` |
| `theme` | `system` | `light`, `dark` or follow the system |
| `sections` | `["japanese"]` | which boxes are shown |
| `color_mode` | `none` | `none`, `grammar`, `pitch` or `difficulty` |
| `story_provider` | `auto` | `auto`, `ollama`, `anthropic` or `none` |
| `ollama_model` | `qwen2.5:7b` | |
| `anthropic_api_key` | `""` | optional |
| `story_model` | `claude-haiku-5-5` | Anthropic model for explanations |
| `japanese_font_size` / `english_font_size` | `20` / `13` | |

### Going offline (optional)

```bash
pip install jamdict jamdict-data      # offline JMdict dictionary (used automatically)
pip install argostranslate
jpshot --setup-offline                # downloads en↔ja translation models
```
then set `"translator": "argos"`. Offline translation quality is noticeably below Google's.

## Platform notes

- **Linux Wayland:** apps can't grab the screen or register global hotkeys. Log in with an X11 session, or start with `QT_QPA_PLATFORM=xcb jpshot` and bind `jpshot capture` to a key in your desktop's keyboard settings.
- **macOS:** grant your terminal **Screen Recording** and **Accessibility** (for the hotkey) in System Settings → Privacy & Security.
- **Windows:** if you want PrintScreen as the hotkey, turn off "Use the Print screen key to open screen capture" in Settings → Accessibility → Keyboard.

## Troubleshooting

Run with `--debug` and watch the terminal: it shows each OCR word with its confidence (and which were dropped), the detected language, the translation, every MeCab token (`surface/reading/dictionary-form/part-of-speech`), dictionary lookups and audio events, plus timings for each step.

- *Nothing happens after selecting* → the log will say `No text detected`; try a larger selection or lower `ocr_min_confidence`.
- *Vertical Japanese* (manga, some novels) isn't supported by the default OCR settings.
- *Odd word boundaries in hover* → OCR mistakes split words oddly; the debug token log shows what MeCab saw.

## How it works

`capture.py` freezes every screen and shows the selection overlay · `ocr.py` runs Tesseract (`jpn+eng`), filters low-confidence words and decides Japanese vs English · `translate.py` translates the other way · `japanese.py` segments the Japanese with MeCab/UniDic (fugashi) to get readings and dictionary forms, and renders Original/Furigana/ひらがな while tracking where every word sits · `dictionary.py` looks words up · `tts.py` synthesizes speech at the chosen speed (cached) · `grammar.py` explains word roles and verb phrases · `kanji.py` builds kanji breakdowns · `furigana_view.py` draws readings above kanji · `ui_result.py` is the window · `settings.py` is the settings dialog · `app.py` ties it together with the tray, hotkey and single-instance socket.
