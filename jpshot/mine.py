"""“Mine” dialog: turn the current capture into an Anki card through AnkiConnect."""
from __future__ import annotations

import base64
import html
import logging
import time
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)

from . import anki
from .workers import run_async

log = logging.getLogger("jpshot.mine")

TEXT_CONTENT = [
    ("japanese", "Japanese sentence"),
    ("furigana", "Furigana (Anki format)"),
    ("hiragana", "Hiragana"),
    ("romaji", "Rōmaji"),
    ("english", "English"),
    ("sentence_cloze", "Sentence with the word blanked"),
    ("selection", "Selected text"),
    ("selection_translation", "Selection translation"),
    ("word", "Word"),
    ("word_furigana", "Word with furigana (Anki format)"),
    ("word_reading", "Word reading"),
    ("word_meaning", "Word meaning"),
    ("word_pos", "Word part of speech"),
    ("notes", "Notes"),
]
WORD_KEYS = ("word_furigana", "word_reading", "word_meaning", "word_pos")
MEDIA_CONTENT = [("image", "Image(s)"), ("audio", "Japanese audio")]
ALL_CONTENT = TEXT_CONTENT + MEDIA_CONTENT
LABEL = dict(ALL_CONTENT)


def guess_content(field_name: str, all_fields: list[str] | None = None) -> str:
    """Best guess at what goes in a note field, from its name (and its siblings' names)."""
    f = field_name.lower()
    others = [x.lower() for x in (all_fields or [])]
    # note types with separate Vocabulary-* fields use "Expression"/"Reading" for the sentence
    has_vocab_fields = any(any(w in o for w in ("vocab", "word")) for o in others)
    wordish = any(w in f for w in ("word", "vocab", "target", "term"))
    sentencey = "sentence" in f or (has_vocab_fields and not wordish)
    if any(k in f for k in ("audio", "sound", "voice")):
        return "audio"
    if any(k in f for k in ("image", "picture", "screenshot", "photo", "pic")):
        return "image"
    if "cloze" in f:
        return "sentence_cloze"
    if any(k in f for k in ("romaji", "romanization")):
        return "romaji"
    if "furigana" in f:
        return "word_furigana" if wordish else "furigana"
    if any(k in f for k in ("pos", "part of speech", "part_of_speech")) and wordish:
        return "word_pos"
    if any(k in f for k in ("kana", "hiragana")) and not wordish:
        return "hiragana"
    if any(k in f for k in ("reading", "kana", "yomi")):
        return "word_reading" if wordish else "furigana"
    if any(k in f for k in ("translation", "english", "meaning", "definition", "gloss")):
        if wordish:
            return "word_meaning"
        return "english" if sentencey or "translation" in f or "english" in f else "word_meaning"
    if "expression" in f:
        return "japanese" if has_vocab_fields else "word"
    if wordish or "kanji" in f:
        return "word"
    if any(k in f for k in ("sentence", "japanese", "front", "text", "question")):
        return "japanese"
    if any(k in f for k in ("back", "answer")):
        return "english"
    if any(k in f for k in ("note", "remark", "hint", "extra")):
        return "notes"
    return ""


def word_fields(query: str, entries) -> dict:
    """Word-related card content from dictionary entries."""
    from .japanese import furigana_parts, has_kanji

    e = entries[0]
    word, reading = e.word or query, e.reading or ""
    if reading and has_kanji(word):
        prefix, core, rcore, suffix = furigana_parts(word, reading)
        furi = f"{prefix}{' ' if prefix else ''}{core}[{rcore}]{suffix}" if rcore else word
    else:
        furi = word
    pos = ", ".join(e.senses[0].pos) if e.senses and e.senses[0].pos else ""
    meaning = "\n".join(f"{i + 1}. {'; '.join(s.glosses)}" for i, s in enumerate(e.senses[:4]))
    return {"word": word, "word_furigana": furi, "word_reading": reading,
            "word_meaning": meaning, "word_pos": pos}


def pixmap_png(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(buf.data())


def _as_field_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def build_and_add(url: str, note: dict, images: list[tuple[bytes, str]], image_fields: list[str],
                  audio_specs: list[dict], voice_field: str = "") -> int:
    """Runs off the UI thread: synthesize audio, attach media, add the note.

    audio_specs: [{"text", "speed", "fields", "voice"} or {..., "random_from": [voice ids] (empty = all)}]
    """
    import random

    from .tts import available_voices, synthesize, voice_name

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if images and image_fields:
        note["picture"] = [
            {"data": base64.b64encode(data).decode(), "filename": f"jpshot-{stamp}-{i}.{ext}",
             "fields": image_fields}
            for i, (data, ext) in enumerate(images)
        ]
    audio = []
    for n, spec in enumerate(audio_specs):
        if not spec.get("text") or not spec.get("fields"):
            continue
        voice = spec.get("voice", "")
        if "random_from" in spec:
            pool = [v.id for v in available_voices() if not spec["random_from"] or v.id in spec["random_from"]]
            voice = random.choice(pool)
            log.info("Hearing card voice: %s", voice_name(voice))
            if voice_field:
                note["fields"][voice_field] = html.escape(voice_name(voice))
        path, _rate = synthesize(spec["text"], spec.get("speed", 1.0), voice)
        audio.append({"data": base64.b64encode(Path(path).read_bytes()).decode(),
                      "filename": f"jpshot-{stamp}-{n}{Path(path).suffix}", "fields": spec["fields"]})
    if audio:
        note["audio"] = audio
    return anki.add_note(url, note)


def ensure_jpshot_model(url: str) -> dict:
    from .anki_model import ensure_model

    ensure_model(url)
    return anki.load_collection_info(url)


class MineDialog(QDialog):
    added = Signal(int)

    def __init__(self, cfg, data: dict, capture_fn, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.data = data
        self.capture_fn = capture_fn
        self.info: dict | None = None
        self.images: list[tuple[bytes, str, QPixmap]] = []   # (bytes, ext, thumbnail source)
        self.field_combos: dict[str, QComboBox] = {}
        self.text_edits: dict[str, QPlainTextEdit] = {}
        self.last_note_id: int | None = None
        self._select_deck_after_load = ""
        self._ignore_saved = False
        self.dictionary = data.get("dictionary")
        self._lookup_id = -1000
        self.setWindowTitle("Mine to Anki")
        self.resize(640, 760)

        # -- Anki target ------------------------------------------------------
        self.status = QLabel("Connecting to Anki…")
        self.status.setWordWrap(True)
        refresh = QToolButton()
        refresh.setText("↻")
        refresh.setToolTip("Reload decks and note types")
        refresh.clicked.connect(self.load_anki)
        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        top.addWidget(refresh)

        target = QGroupBox("Anki")
        tf = QFormLayout(target)
        self.deck = QComboBox()
        self.deck.setEditable(False)
        self.new_deck_btn = QPushButton("+ New deck…")
        self.new_deck_btn.setToolTip("Create a new Anki deck (use Parent::Child for a subdeck)")
        self.new_deck_btn.setEnabled(False)
        self.new_deck_btn.clicked.connect(self._new_deck)
        deck_row = QHBoxLayout()
        deck_row.addWidget(self.deck, 1)
        deck_row.addWidget(self.new_deck_btn)
        tf.addRow("Deck", deck_row)
        self.model = QComboBox()
        self.model.currentTextChanged.connect(self._model_changed)
        self.jps_btn = QPushButton("Use JPShot card type")
        self.jps_btn.setToolTip("Create (or update) the “JPShot Sentence” note type in Anki and use it:\n"
                                "Reading and Hearing cards, random fonts, audio on the back")
        self.jps_btn.setEnabled(False)
        self.jps_btn.clicked.connect(self._use_jpshot_model)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.jps_btn)
        tf.addRow("Note type", model_row)
        self.tags = QLineEdit(cfg.anki_tags)
        self.tags.setPlaceholderText("space-separated tags")
        tf.addRow("Tags", self.tags)

        self.jps_box = QGroupBox("JPShot cards")
        jl = QVBoxLayout(self.jps_box)
        self.make_reading = QCheckBox("Reading card — front: image + Japanese; back: furigana, English, "
                                      "image, audio (plays automatically)")
        self.make_reading.setChecked(bool(cfg.anki_reading))
        self.make_hearing = QCheckBox("Hearing card — front: image + audio in a random voice; back: "
                                      "furigana, English (audio doesn't replay)")
        self.make_hearing.setChecked(bool(cfg.anki_hearing))
        self.random_font = QCheckBox("Random font and size for the Japanese on the Reading front "
                                     "(🔀 on the card reshuffles)")
        self.random_font.setChecked(bool(cfg.anki_random_font))
        for w in (self.make_reading, self.make_hearing, self.random_font):
            w.setStyleSheet("QCheckBox { padding: 2px 0; }")
            jl.addWidget(w)
        self.jps_box.hide()

        self.map_box = QGroupBox("What goes in each field")
        map_outer = QVBoxLayout(self.map_box)
        self.map_form = QFormLayout()
        map_outer.addLayout(self.map_form)
        reguess = QToolButton()
        reguess.setText("Guess fields again")
        reguess.setToolTip("Forget the saved choices for this note type and guess from the field names")
        reguess.clicked.connect(self._reguess)
        map_outer.addWidget(reguess, 0, Qt.AlignmentFlag.AlignRight)

        # -- content ----------------------------------------------------------
        content = QGroupBox("Card content (edit freely)")
        cf = QFormLayout(content)
        for key, label in TEXT_CONTENT:
            ed = QPlainTextEdit(self.data.get(key, ""))
            ed.setFixedHeight(54 if key not in ("notes",) else 44)
            self.text_edits[key] = ed
            if key == "word":
                ed.setFixedHeight(34)
                row = QHBoxLayout()
                row.addWidget(ed, 1)
                look = QPushButton("Look up")
                look.setToolTip("Fill the word's furigana, reading, meaning and part of speech")
                look.clicked.connect(self._lookup_word)
                row.addWidget(look)
                cf.addRow(label, row)
                continue
            cf.addRow(label, ed)

        # images
        img_box = QGroupBox("Images")
        il = QVBoxLayout(img_box)
        self.thumbs = QHBoxLayout()
        self.thumbs.addStretch()
        thumbs_w = QWidget()
        thumbs_w.setLayout(self.thumbs)
        thumbs_scroll = QScrollArea()
        thumbs_scroll.setWidgetResizable(True)
        thumbs_scroll.setFixedHeight(120)
        thumbs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        thumbs_scroll.setWidget(thumbs_w)
        il.addWidget(thumbs_scroll)
        ib = QHBoxLayout()
        shot = QPushButton("📷 Take another screenshot")
        shot.clicked.connect(self._take_screenshot)
        ib.addWidget(shot)
        fileb = QPushButton("Add image file…")
        fileb.clicked.connect(self._add_file)
        ib.addWidget(fileb)
        paste = QPushButton("Paste image")
        paste.clicked.connect(self._paste)
        ib.addWidget(paste)
        ib.addStretch()
        il.addLayout(ib)

        # audio
        self.audio = QCheckBox("Include Japanese audio of the sentence")
        self.audio.setChecked(bool(cfg.anki_audio))

        self.dup = QCheckBox("Allow duplicates")

        self.add_btn = QPushButton("Add card")
        self.add_btn.setDefault(True)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        self.show_btn = QPushButton("Show in Anki")
        self.show_btn.setVisible(False)
        self.show_btn.clicked.connect(self._show_in_anki)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self.dup)
        bottom.addStretch()
        bottom.addWidget(self.show_btn)
        bottom.addWidget(close)
        bottom.addWidget(self.add_btn)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.addWidget(target)
        lay.addWidget(self.jps_box)
        lay.addWidget(self.map_box)
        lay.addWidget(content)
        lay.addWidget(img_box)
        lay.addWidget(self.audio)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(scroll, 1)
        root.addLayout(bottom)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._add)

        pm = data.get("pixmap")
        if pm is not None and not pm.isNull():
            self._add_pixmap(pm)
        self.load_anki()

    # -- Anki info --------------------------------------------------------
    def load_anki(self):
        self.status.setText("Connecting to Anki…")
        run_async(anki.load_collection_info, self.cfg.anki_url,
                  on_done=self._anki_loaded, on_error=self._anki_failed)

    def _anki_failed(self, msg):
        log.error("Anki: %s", msg)
        self.status.setText(f"<span style='color:#d44'>{html.escape(msg.split(': ', 1)[-1])}</span>")
        self.add_btn.setEnabled(False)

    def _anki_loaded(self, info):
        self.info = info
        self.status.setText(f"Connected to Anki · {len(info['decks'])} decks")
        for combo, items, want in ((self.deck, info["decks"], self.cfg.anki_deck),
                                   (self.model, info["models"], self.cfg.anki_model)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            if want in items:
                combo.setCurrentText(want)
            combo.blockSignals(False)
        self._model_changed(self.model.currentText())
        self.add_btn.setEnabled(bool(info["decks"] and info["models"]))
        self.new_deck_btn.setEnabled(True)
        self.jps_btn.setEnabled(True)
        if self._select_deck_after_load:
            self.deck.setCurrentText(self._select_deck_after_load)
            self._select_deck_after_load = ""

    def _new_deck(self):
        name, ok = QInputDialog.getText(self, "New Anki deck",
                                        "Deck name (use Parent::Child to make a subdeck):",
                                        text="JPShot")
        name = name.strip()
        if not ok or not name:
            return
        if self.info and name in self.info["decks"]:
            self.deck.setCurrentText(name)
            self.status.setText(f"Deck “{html.escape(name)}” already exists — selected it")
            return
        self.status.setText(f"Creating deck “{html.escape(name)}”…")
        self.new_deck_btn.setEnabled(False)
        run_async(anki.create_deck, self.cfg.anki_url, name,
                  on_done=lambda _id: self._deck_created(name),
                  on_error=self._deck_failed)

    def _deck_created(self, name: str):
        self.cfg.anki_deck = name
        self.cfg.save()
        self._select_deck_after_load = name
        self.load_anki()

    def _deck_failed(self, msg):
        self.new_deck_btn.setEnabled(True)
        self.status.setText(f"<span style='color:#d44'>Could not create deck: "
                            f"{html.escape(msg.split(': ', 1)[-1])}</span>")

    def _use_jpshot_model(self):
        self.status.setText("Setting up the JPShot card type in Anki…")
        self.jps_btn.setEnabled(False)
        run_async(ensure_jpshot_model, self.cfg.anki_url,
                  on_done=self._jpshot_model_ready, on_error=self._anki_failed)

    def _jpshot_model_ready(self, info):
        from .anki_model import MODEL_NAME

        self.cfg.anki_model = MODEL_NAME
        self._anki_loaded(info)
        self.model.setCurrentText(MODEL_NAME)
        self.status.setText("Using the JPShot Sentence card type")

    def _is_jpshot_model(self) -> bool:
        from .anki_model import MODEL_NAME
        return self.model.currentText() == MODEL_NAME

    def _reguess(self):
        self._ignore_saved = True
        self._model_changed(self.model.currentText())
        self._ignore_saved = False

    # -- word lookup ------------------------------------------------------
    def _lookup_word(self):
        word = self.text_edits["word"].toPlainText().strip()
        if not word:
            self.status.setText("Type or paste a word in the Word box first")
            return
        if self.dictionary is None:
            return
        self._lookup_id -= 1
        try:
            self.dictionary.finished.disconnect(self._word_found)
        except (RuntimeError, TypeError):
            pass
        self.dictionary.finished.connect(self._word_found)
        self.status.setText(f"Looking up {html.escape(word)}…")
        self.dictionary.lookup(self._lookup_id, [word])

    def _word_found(self, req_id, query, entries, error):
        if req_id != self._lookup_id:
            return
        if error or not entries:
            self.status.setText(html.escape(error or "No dictionary entry found for that word"))
            return
        fill = word_fields(query, entries)
        for k, v in fill.items():
            self.text_edits[k].setPlainText(v)
        self.status.setText(f"Filled in {html.escape(query)}")

    def _model_changed(self, model: str):
        jps = self._is_jpshot_model()
        self.jps_box.setVisible(jps)
        self.map_box.setVisible(not jps)
        self.audio.setVisible(not jps)
        while self.map_form.rowCount():
            self.map_form.removeRow(0)
        self.field_combos.clear()
        if not self.info or model not in self.info["fields"]:
            return
        saved = self.cfg.anki_field_map.get(model, {})
        for fname in self.info["fields"][model]:
            c = QComboBox()
            c.addItem("— nothing —", "")
            for key, label in ALL_CONTENT:
                c.addItem(label, key)
            guess = guess_content(fname, self.info["fields"][model])
            want = saved.get(fname, guess) if saved and not self._ignore_saved else guess
            i = c.findData(want)
            c.setCurrentIndex(max(0, i))
            self.field_combos[fname] = c
            self.map_form.addRow(fname, c)

    # -- images -----------------------------------------------------------
    def _add_pixmap(self, pm: QPixmap):
        self.images.append((pixmap_png(pm), "png", pm))
        self._refresh_thumbs()

    def _refresh_thumbs(self):
        while self.thumbs.count() > 1:
            item = self.thumbs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, (_data, _ext, pm) in enumerate(self.images):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel()
            lbl.setPixmap(pm.scaled(150, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            v.addWidget(lbl)
            rm = QToolButton()
            rm.setText("✕ remove")
            rm.setAutoRaise(True)
            rm.clicked.connect(lambda _=False, k=i: self._remove_image(k))
            v.addWidget(rm, 0, Qt.AlignmentFlag.AlignHCenter)
            self.thumbs.insertWidget(self.thumbs.count() - 1, w)

    def _remove_image(self, i: int):
        if 0 <= i < len(self.images):
            del self.images[i]
            self._refresh_thumbs()

    def _take_screenshot(self):
        log.info("Mining: capturing another screenshot")
        self.capture_fn(self._add_pixmap)

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add image", str(Path.home()),
                                              "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            self.status.setText("That file isn't an image Qt can read")
            return
        ext = Path(path).suffix.lower().lstrip(".") or "png"
        self.images.append((Path(path).read_bytes(), ext, pm))
        self._refresh_thumbs()

    def _paste(self):
        img: QImage = QGuiApplication.clipboard().image()
        if img.isNull():
            self.status.setText("No image on the clipboard")
            return
        self._add_pixmap(QPixmap.fromImage(img))

    # -- add --------------------------------------------------------------
    def _add(self):
        if not self.info or not self.add_btn.isEnabled():
            return
        if self._is_jpshot_model():
            self._add_jpshot()
            return
        model, deck = self.model.currentText(), self.deck.currentText()
        mapping = {f: c.currentData() for f, c in self.field_combos.items()}
        fields, image_fields, audio_fields = {}, [], []
        for fname, key in mapping.items():
            if key == "image":
                image_fields.append(fname)
            elif key == "audio":
                audio_fields.append(fname)
            elif key:
                fields[fname] = _as_field_html(self.text_edits[key].toPlainText().strip())
            else:
                fields[fname] = ""
        note = {
            "deckName": deck, "modelName": model, "fields": fields,
            "tags": self.tags.text().split(),
            "options": {"allowDuplicate": self.dup.isChecked(), "duplicateScope": "deck"},
        }
        first = self.info["fields"].get(model, [""])[0]
        if first and not fields.get(first, "").strip():
            what = LABEL.get(mapping.get(first, ""), "nothing")
            hint = (" Shift-hover a word before mining, or type it in the Word box and press Look up."
                    if mapping.get(first, "").startswith("word") else "")
            self.status.setText(
                f"<span style='color:#d44'>Anki needs the first field, <b>{html.escape(first)}</b>, "
                f"to have something in it. It's set to “{html.escape(what)}”, which is empty.{hint}</span>")
            return
        audio_text = self.data.get("audio_text", "") if self.audio.isChecked() else ""
        if self.audio.isChecked() and not audio_fields:
            self.status.setText("Pick a field for “Japanese audio” (or untick the audio box)")
            return
        if self.images and not image_fields:
            log.info("Images not attached: no field is set to “Image(s)”")

        # remember choices
        self.cfg.anki_deck, self.cfg.anki_model = deck, model
        self.cfg.anki_tags = self.tags.text()
        self.cfg.anki_audio = self.audio.isChecked()
        self.cfg.anki_field_map = {**self.cfg.anki_field_map, model: mapping}
        self.cfg.save()

        self.add_btn.setEnabled(False)
        self.status.setText("Adding card…" + (" (generating audio)" if audio_text else ""))
        log.info("Mining to deck %r, note type %r, fields %s, %d image(s), audio=%s",
                 deck, model, list(fields), len(self.images) if image_fields else 0, bool(audio_text))
        run_async(build_and_add, self.cfg.anki_url, note,
                  [(d, e) for d, e, _ in self.images], image_fields,
                  [{"text": audio_text, "voice": self.cfg.voice, "fields": audio_fields,
                    "speed": float(self.data.get("speed", 1.0))}],
                  on_done=self._added, on_error=self._add_failed)

    def _add_jpshot(self):
        from .anki_model import MODEL_NAME

        reading, hearing = self.make_reading.isChecked(), self.make_hearing.isChecked()
        if not (reading or hearing):
            self.status.setText("Tick Reading card, Hearing card, or both")
            return
        t = {k: e.toPlainText().strip() for k, e in self.text_edits.items()}
        sentence = t["japanese"]
        if not sentence:
            self.status.setText("The Japanese sentence is empty")
            return
        fields = {
            "Sentence": _as_field_html(sentence),
            "Furigana": _as_field_html(t["furigana"] or sentence),
            "English": _as_field_html(t["english"]),
            "Word": _as_field_html(t["word_furigana"] or t["word"]),
            "WordReading": _as_field_html(t["word_reading"]),
            "WordMeaning": _as_field_html(t["word_meaning"]),
            "Notes": _as_field_html(t["notes"]),
            "Reading": "1" if reading else "",
            "Hearing": "1" if hearing else "",
            "RandomFont": "1" if self.random_font.isChecked() else "",
            "Voice": "",
        }
        note = {"deckName": self.deck.currentText(), "modelName": MODEL_NAME, "fields": fields,
                "tags": self.tags.text().split(),
                "options": {"allowDuplicate": self.dup.isChecked(), "duplicateScope": "deck"}}
        audio_text = self.data.get("audio_text", "") or sentence.replace("\n", "")
        speed = float(self.data.get("speed", 1.0))
        specs = []
        if reading:
            specs.append({"text": audio_text, "voice": self.cfg.voice, "speed": speed, "fields": ["Audio"]})
        if hearing:
            specs.append({"text": audio_text, "random_from": list(self.cfg.hearing_voices),
                          "speed": speed, "fields": ["HearingAudio"]})

        self.cfg.anki_deck, self.cfg.anki_model = self.deck.currentText(), MODEL_NAME
        self.cfg.anki_tags = self.tags.text()
        self.cfg.anki_reading, self.cfg.anki_hearing = reading, hearing
        self.cfg.anki_random_font = self.random_font.isChecked()
        self.cfg.save()

        self.add_btn.setEnabled(False)
        self.status.setText("Adding card… (generating audio)")
        log.info("Mining JPShot card: reading=%s hearing=%s random_font=%s, %d image(s)",
                 reading, hearing, self.random_font.isChecked(), len(self.images))
        run_async(build_and_add, self.cfg.anki_url, note, [(d, e) for d, e, _ in self.images], ["Image"],
                  specs, "Voice", on_done=self._added, on_error=self._add_failed)

    def _added(self, nid):
        self.last_note_id = nid
        self.status.setText("<b style='color:#2fb383'>Card added ✓</b>")
        self.show_btn.setVisible(True)
        self.add_btn.setEnabled(True)
        self.add_btn.setText("Add again")
        self.added.emit(nid)

    def _add_failed(self, msg):
        msg = msg.split(": ", 1)[-1]
        if "duplicate" in msg.lower():
            msg += " — tick “Allow duplicates” to add it anyway."
        self.status.setText(f"<span style='color:#d44'>Could not add: {html.escape(msg)}</span>")
        self.add_btn.setEnabled(True)

    def _show_in_anki(self):
        if self.last_note_id:
            run_async(anki.browse, self.cfg.anki_url, self.last_note_id,
                      on_error=lambda m: self.status.setText(html.escape(m)))
