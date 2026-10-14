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
    ("selection", "Selected text"),
    ("selection_translation", "Selection translation"),
    ("word", "Word (last looked up)"),
    ("word_reading", "Word reading"),
    ("word_meaning", "Word meaning"),
    ("notes", "Notes"),
]
MEDIA_CONTENT = [("image", "Image(s)"), ("audio", "Japanese audio")]
ALL_CONTENT = TEXT_CONTENT + MEDIA_CONTENT
LABEL = dict(ALL_CONTENT)


def guess_content(field_name: str) -> str:
    """Best guess at what goes in a note field, from its name."""
    f = field_name.lower()
    wordish = any(w in f for w in ("word", "vocab", "target", "term"))
    rules = [
        (("audio", "sound", "voice"), "audio"),
        (("image", "picture", "screenshot", "photo", "pic"), "image"),
        (("furigana",), "furigana"),
        (("romaji", "romanization"), "romaji"),
        (("reading", "kana", "yomi"), "word_reading" if wordish else "furigana"),
        (("translation", "english", "sentence meaning", "sentence_meaning"), "english"),
        (("meaning", "definition", "gloss"), "word_meaning" if wordish or "sentence" not in f else "english"),
        (("word", "vocab", "expression", "target", "term"), "word"),
        (("sentence", "japanese", "front", "text", "question"), "japanese"),
        (("back", "answer"), "english"),
        (("note", "remark", "hint", "extra"), "notes"),
    ]
    for keys, content in rules:
        if any(k in f for k in keys):
            return content
    return ""


def pixmap_png(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(buf.data())


def _as_field_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def build_and_add(url: str, note: dict, images: list[tuple[bytes, str]], image_fields: list[str],
                  audio_text: str, audio_fields: list[str], speed: float, engine: str, voice: str) -> int:
    """Runs off the UI thread: synthesize audio if needed, attach media, add the note."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if images and image_fields:
        note["picture"] = [
            {"data": base64.b64encode(data).decode(), "filename": f"jpshot-{stamp}-{i}.{ext}",
             "fields": image_fields}
            for i, (data, ext) in enumerate(images)
        ]
    if audio_text and audio_fields:
        from .tts import synthesize

        path, _rate = synthesize(audio_text, speed, engine, voice)
        note["audio"] = [{"data": base64.b64encode(Path(path).read_bytes()).decode(),
                          "filename": f"jpshot-{stamp}.mp3", "fields": audio_fields}]
    return anki.add_note(url, note)


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
        tf.addRow("Note type", self.model)
        self.tags = QLineEdit(cfg.anki_tags)
        self.tags.setPlaceholderText("space-separated tags")
        tf.addRow("Tags", self.tags)

        self.map_box = QGroupBox("What goes in each field")
        self.map_form = QFormLayout(self.map_box)

        # -- content ----------------------------------------------------------
        content = QGroupBox("Card content (edit freely)")
        cf = QFormLayout(content)
        for key, label in TEXT_CONTENT:
            ed = QPlainTextEdit(self.data.get(key, ""))
            ed.setFixedHeight(54 if key not in ("notes",) else 44)
            self.text_edits[key] = ed
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

    def _model_changed(self, model: str):
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
            want = saved.get(fname, guess_content(fname)) if saved else guess_content(fname)
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
                  audio_text, audio_fields, float(self.data.get("speed", 1.0)),
                  self.cfg.tts_engine, self.cfg.tts_voice,
                  on_done=self._added, on_error=self._add_failed)

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
