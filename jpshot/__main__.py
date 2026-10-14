"""Terminal entry point.

    python -m jpshot              start JPShot (tray + hotkey), logs to this terminal
    python -m jpshot capture      start a capture (in the running instance, or start one)
    python -m jpshot file IMG     run the OCR/translate window on an image file
    python -m jpshot ocr IMG      terminal only: print OCR text, language and translation
    python -m jpshot check        check that every dependency is installed and working
    python -m jpshot settings     open the settings window
    python -m jpshot history      browse past captures
    python -m jpshot quit         stop the running instance

Options:  --debug  verbose logs     --setup-offline  install offline translation models
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys

from . import __version__
from .config import Config
from .log import setup as setup_logging

log = logging.getLogger("jpshot")


def cmd_check(cfg: Config) -> int:
    ok = True

    def report(name, fn):
        nonlocal ok
        try:
            detail = fn()
            print(f"  \033[32m✔\033[0m {name}: {detail}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  \033[31m✘\033[0m {name}: {type(e).__name__}: {e}")

    def tess():
        import pytesseract
        from . import ocr
        ocr.configure(cfg.tesseract_cmd)
        langs = pytesseract.get_languages(config="")
        missing = [l for l in ("jpn", "eng") if l not in langs]
        if missing:
            raise RuntimeError(f"missing language data: {', '.join(missing)}")
        return f"v{pytesseract.get_tesseract_version()} with jpn+eng"

    def tok():
        from . import japanese
        toks = japanese.tokenize("日本語を勉強しています")[0]
        return " | ".join(f"{t.surface}({t.reading})" for t in toks)

    def trans():
        from . import translate
        return translate.translate("こんにちは", "ja", "en", cfg.translator)

    def dic():
        from PySide6.QtCore import QCoreApplication
        from .dictionary import Dictionary
        QCoreApplication.instance() or QCoreApplication([])
        d = Dictionary(cfg.dictionary)
        entries = d._lookup_one("食べる")
        return f"{'jamdict (offline)' if d._jam and not d._jam_failed else 'jisho.org'}: 食べる = " \
               + "; ".join(entries[0].senses[0].glosses[:3])

    def tts():
        from .tts import synthesize
        from .tts import available_voices
        path, rate = synthesize("テスト", 1.0, cfg.voice)
        vv = [v for v in available_voices() if v.engine in ("voicevox", "aivis")]
        extra = f"; {len(vv)} VOICEVOX/AivisSpeech voices" if vv else "; VOICEVOX not running (optional)"
        return f"{cfg.voice} → {path.name} ({path.stat().st_size} bytes){extra}"

    def qt():
        import PySide6
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
        return f"PySide6 {PySide6.__version__} with QtMultimedia"

    def hotkey():
        import pynput  # noqa: F401
        return f"pynput available, hotkey {cfg.hotkey or '(disabled)'}"

    print(f"JPShot {__version__} — config: {Config.path()}")
    for name, fn in [("Qt", qt), ("Tesseract OCR", tess), ("Japanese tokenizer", tok),
                     ("Translation", trans), ("Dictionary", dic), ("Text-to-speech", tts),
                     ("Global hotkey", hotkey)]:
        report(name, fn)
    print("All good!" if ok else "Some components failed — see README for install steps.")
    return 0 if ok else 1


def cmd_ocr(cfg: Config, path: str) -> int:
    from PIL import Image
    from . import japanese, ocr, translate

    ocr.configure(cfg.tesseract_cmd)
    res = ocr.recognize(Image.open(path), cfg.ocr_languages, cfg.ocr_min_confidence, cfg.ocr_min_chars)
    if res is None:
        print("No text detected.")
        return 1
    src, dst = ("ja", "en") if res.language == "ja" else ("en", "ja")
    out = translate.translate(ocr.flatten(res.text, res.language), src, dst, cfg.translator)
    ja = res.text if src == "ja" else out
    lines = japanese.tokenize(ja)
    print(f"\n[{src} → {dst}]  confidence {res.confidence:.0f}%\n")
    print("Source:     ", res.text.replace("\n", "\n             "))
    print("Translation:", out)
    print("Furigana:   ", japanese.render(lines, "furigana")[0])
    print("Hiragana:   ", japanese.render(lines, "hiragana")[0])
    print("Romaji:     ", japanese.render(lines, "romaji")[0])
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jpshot", description="Screenshot → OCR → English/Japanese study popup")
    p.add_argument("command", nargs="?", default="run",
                   choices=["run", "capture", "file", "ocr", "check", "quit", "show", "settings", "history"])
    p.add_argument("image", nargs="?", help="image path for `file` / `ocr`")
    p.add_argument("--debug", "-d", action="store_true", help="verbose debug logging")
    p.add_argument("--setup-offline", action="store_true", help="install Argos offline translation models")
    p.add_argument("--version", action="version", version=f"jpshot {__version__}")
    args = p.parse_args(argv)

    setup_logging(args.debug)
    cfg = Config.load()
    from dataclasses import asdict
    log.debug("Config %s: %s", Config.path(),
              {k: ("***" if k == "anthropic_api_key" and v else v) for k, v in asdict(cfg).items()})

    if args.setup_offline:
        from .translate import install_offline_models
        install_offline_models()
        return 0
    if args.command == "check":
        return cmd_check(cfg)
    if args.command in ("file", "ocr") and not args.image:
        p.error(f"`{args.command}` needs an image path")
    if args.image:
        import os
        if not os.path.isfile(args.image):
            p.error(f"image not found: {args.image}")
    if args.command == "ocr":
        return cmd_ocr(cfg, args.image)

    from PySide6.QtCore import QRect, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("JPShot")
    app.setQuitOnLastWindowClosed(False)

    from .app import JPShotApp, make_icon, send_to_running

    if args.command in ("capture", "quit", "show", "settings", "history") and send_to_running(args.command):
        return 0
    if args.command in ("quit", "show"):
        log.info("JPShot is not running")
        return 1
    if args.command == "run" and send_to_running("noop"):
        log.info("JPShot is already running. Use `python -m jpshot capture` or the hotkey.")
        return 0

    from . import theme
    theme.apply(cfg.theme)
    app.setWindowIcon(make_icon())
    jp = JPShotApp(cfg)
    log.info("JPShot %s running. Hotkey: %s  ·  Ctrl+C here to quit.", __version__, cfg.hotkey or "(none)")

    # Let Ctrl+C in the terminal stop the Qt event loop.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(250)

    if args.command == "capture":
        QTimer.singleShot(400, jp.start_capture)
    elif args.command == "settings":
        QTimer.singleShot(100, jp.open_settings)
    elif args.command == "history":
        QTimer.singleShot(100, jp.result.open_history)
    elif args.command == "file":
        from PIL import Image
        img = Image.open(args.image).convert("RGB")
        scr = QGuiApplication.primaryScreen().availableGeometry()
        anchor = QRect(scr.center().x() - 300, scr.top() + 80, 1, 1)
        from PySide6.QtGui import QPixmap
        pm = QPixmap(args.image)
        QTimer.singleShot(200, lambda: jp.process_image(img, anchor, pm))

    code = app.exec()
    jp.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
