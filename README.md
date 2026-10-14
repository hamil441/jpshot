# JPShot

A Flameshot-style screenshot tool for learning Japanese. Press the hotkey, drag around any text on screen, and if JPShot finds English or Japanese text it pops up a window with:

- **English** — the text in English (OCR'd or translated), selectable and copyable.
- **日本語 Japanese** — the text in Japanese, with a one-click switch between **Original**, **Furigana** (`食(た)べる`) and **ひらがな**. Hold **Shift** and hover any word to see its dictionary entry (dictionary form, reading, meanings, part of speech).
- **Read in Japanese** — neural Japanese text-to-speech with a **speed slider** (0.5× – 2×) always visible at the bottom.

If no text is detected, nothing happens.

Everything is logged to the terminal you start it from (add `--debug` for full detail).

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
jpshot quit            # stop the running instance
```

Without installing, replace `jpshot` with `python -m jpshot`.

Default hotkey: **Ctrl+Alt+J**. Left-clicking the tray icon also starts a capture.

## Using it

| Where | Key / action | Does |
|---|---|---|
| Capture | drag | select a region |
| Capture | Esc / right-click | cancel |
| Result | Shift + hover a Japanese word | dictionary popup |
| Result | Esc | close popup, then the window |
| Result | Space | play / stop audio |
| Result | `[` / `]` | slower / faster speech |
| Result | Alt+1 / Alt+2 / Alt+3 | Original / Furigana / ひらがな |
| Result | Ctrl+1 / Ctrl+2 | English / Japanese tab |

Changing the speed while audio is playing restarts it at the new speed from about the same spot. Your speed, display mode and tab are remembered.

## Configuration

Settings live in `config.json` (path shown by `jpshot check`; on Linux `~/.config/jpshot/`, Windows `%APPDATA%\jpshot\`, macOS `~/Library/Application Support/jpshot/`).

| Key | Default | Notes |
|---|---|---|
| `hotkey` | `<ctrl>+<alt>+j` | pynput syntax, e.g. `<cmd>+<shift>+j`, `<print_screen>`. `""` disables it |
| `tesseract_cmd` | `""` | full path if Tesseract isn't found automatically |
| `ocr_min_confidence` | `55` | raise it if you get garbage text, lower it if text is missed |
| `translator` | `google` | or `argos` for offline (see below) |
| `tts_engine` | `edge` | Microsoft neural voices (online); falls back to `gtts` |
| `tts_voice` | `ja-JP-NanamiNeural` | or `ja-JP-KeitaNeural` (male) |
| `dictionary` | `auto` | offline JMdict if installed, else jisho.org; or force `jamdict` / `jisho` |
| `japanese_font_size` | `20` | |

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

`capture.py` freezes every screen and shows the selection overlay · `ocr.py` runs Tesseract (`jpn+eng`), filters low-confidence words and decides Japanese vs English · `translate.py` translates the other way · `japanese.py` segments the Japanese with MeCab/UniDic (fugashi) to get readings and dictionary forms, and renders Original/Furigana/ひらがな while tracking where every word sits · `dictionary.py` looks words up · `tts.py` synthesizes speech at the chosen speed (cached) · `ui_result.py` is the window · `app.py` ties it together with the tray, hotkey and single-instance socket.
