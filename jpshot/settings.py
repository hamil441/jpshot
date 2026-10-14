"""Settings dialog: edits config.json and applies changes immediately."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSpinBox, QToolButton, QVBoxLayout)

from .config import ALL_SECTIONS, Config
from .workers import run_async

log = logging.getLogger("jpshot.settings")

SECTION_LABELS = {"english": "English", "japanese": "日本語 (original)", "furigana": "Furigana",
                  "hiragana": "ひらがな", "romaji": "Rōmaji"}
VOICES = [("ja-JP-NanamiNeural", "Nanami (female)"), ("ja-JP-KeitaNeural", "Keita (male)")]


def _combo(options, current):
    c = QComboBox()
    for value, label in options:
        c.addItem(label, value)
    i = c.findData(current)
    if i < 0:  # value not in the list (hand-edited config): keep it
        c.addItem(str(current), current)
        i = c.count() - 1
    c.setCurrentIndex(i)
    return c


class SettingsDialog(QDialog):
    applied = Signal()  # emitted after config is saved

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("JPShot settings")
        self.setMinimumWidth(460)

        # -- Capture --------------------------------------------------------
        cap = QGroupBox("Capture")
        f = QFormLayout(cap)
        self.hotkey = QLineEdit(cfg.hotkey)
        self.hotkey.setPlaceholderText("empty = no hotkey (bind `jpshot capture` in your WM)")
        self.hotkey.setToolTip("pynput syntax, e.g. <shift>+<print_screen>, <ctrl>+<alt>+j")
        f.addRow("Global hotkey", self.hotkey)
        self.tesseract = QLineEdit(cfg.tesseract_cmd)
        self.tesseract.setPlaceholderText("auto-detect")
        f.addRow("Tesseract path", self.tesseract)
        self.min_conf = QSpinBox()
        self.min_conf.setRange(0, 100)
        self.min_conf.setValue(int(cfg.ocr_min_confidence))
        self.min_conf.setToolTip("Raise if you get garbage text, lower if text is missed")
        f.addRow("OCR min confidence", self.min_conf)

        # -- Language services --------------------------------------------------
        svc = QGroupBox("Translation, voice & dictionary")
        f = QFormLayout(svc)
        self.translator = _combo([("google", "Google (with automatic fallbacks)"),
                                  ("mymemory", "MyMemory first"),
                                  ("argos", "Argos (offline only)")], cfg.translator)
        f.addRow("Translator", self.translator)
        self.voice = QComboBox()
        self.voice.addItem(cfg.voice, cfg.voice)
        refresh = QToolButton()
        refresh.setText("↻")
        refresh.setToolTip("Look for VOICEVOX / AivisSpeech voices again")
        refresh.clicked.connect(lambda: self._load_voices(True))
        vrow = QHBoxLayout()
        vrow.addWidget(self.voice, 1)
        vrow.addWidget(refresh)
        f.addRow("Voice", vrow)
        self.hearing = QListWidget()
        self.hearing.setFixedHeight(120)
        self.hearing.setToolTip("Hearing cards use a random voice from the ticked ones (none ticked = all)")
        f.addRow("Hearing-card voices", self.hearing)
        self.voice_hint = QLabel()
        self.voice_hint.setWordWrap(True)
        self.voice_hint.setStyleSheet("color:gray")
        f.addRow(self.voice_hint)
        self.dictionary = _combo([("auto", "Auto (offline if installed, else jisho.org)"),
                                  ("jamdict", "Offline JMdict (jamdict)"),
                                  ("jisho", "jisho.org")], cfg.dictionary)
        f.addRow("Dictionary", self.dictionary)

        # -- Kanji stories ---------------------------------------------------
        story = QGroupBox("Kanji stories (optional)")
        f = QFormLayout(story)
        self.api_key = QLineEdit(cfg.anthropic_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Anthropic API key (sk-ant-…) — leave empty to skip")
        f.addRow("API key", self.api_key)
        self.story_model = QLineEdit(cfg.story_model)
        f.addRow("Model", self.story_model)
        expl = QLabel("With a key, each kanji gets a short (≤3 sentence) Remembering-the-Kanji-style "
                      "story, written once and saved. Without one, JPShot shows how the parts are laid out "
                      "and where the character comes from. The key is stored in config.json.")
        expl.setWordWrap(True)
        expl.setStyleSheet("color:gray")
        f.addRow(expl)

        # -- Look -----------------------------------------------------------
        look = QGroupBox("Appearance")
        f = QFormLayout(look)
        self.theme = _combo([("system", "Follow system"), ("light", "Light"), ("dark", "Dark")], cfg.theme)
        f.addRow("Theme", self.theme)
        self.lookup_key = _combo([("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt"), ("meta", "Super / Windows key")],
                                 cfg.lookup_key)
        self.lookup_key.setToolTip("Hold this key over a Japanese word to see its dictionary, grammar and kanji")
        f.addRow("Word popup key", self.lookup_key)
        self.ja_size = QSpinBox()
        self.ja_size.setRange(10, 48)
        self.ja_size.setValue(int(cfg.japanese_font_size))
        f.addRow("Japanese font size", self.ja_size)
        self.en_size = QSpinBox()
        self.en_size.setRange(8, 36)
        self.en_size.setValue(int(cfg.english_font_size))
        f.addRow("English font size", self.en_size)
        row = QHBoxLayout()
        self.section_boxes = {}
        for key in ALL_SECTIONS:
            cb = QCheckBox(SECTION_LABELS[key])
            cb.setChecked(key in cfg.sections)
            self.section_boxes[key] = cb
            row.addWidget(cb)
        f.addRow("Show", row)

        # -- Buttons --------------------------------------------------------
        open_file = QPushButton("Open config.json")
        open_file.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Config.path()))))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        bottom = QHBoxLayout()
        bottom.addWidget(open_file)
        bottom.addStretch()
        bottom.addWidget(buttons)

        note = QLabel(f"Saved to {Config.path()}")
        note.setStyleSheet("color:gray")
        note.setWordWrap(True)

        self._load_voices()

        lay = QVBoxLayout(self)
        for g in (cap, svc, story, look):
            lay.addWidget(g)
        lay.addWidget(note)
        lay.addLayout(bottom)

    def _load_voices(self, refresh=False):
        from .tts import available_voices

        self.voice_hint.setText("Looking for voices…")
        run_async(available_voices, refresh, on_done=self._voices_loaded)

    def _voices_loaded(self, voices):
        current = self.voice.currentData() or self.cfg.voice
        self.voice.clear()
        self.hearing.clear()
        for v in voices:
            self.voice.addItem(v.name, v.id)
            item = QListWidgetItem(v.name)
            item.setData(Qt.ItemDataRole.UserRole, v.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if v.id in self.cfg.hearing_voices
                               else Qt.CheckState.Unchecked)
            self.hearing.addItem(item)
        i = self.voice.findData(current)
        self.voice.setCurrentIndex(max(0, i))
        local = sum(1 for v in voices if v.engine in ("voicevox", "aivis"))
        if local:
            self.voice_hint.setText(f"{len(voices)} voices, including {local} from VOICEVOX/AivisSpeech "
                                    "(keep that app running to use them).")
        else:
            self.voice_hint.setText("Want more voices? Install VOICEVOX (free; on Arch: the AUR package "
                                    "“voicevox”), keep it running, then press ↻ — it adds dozens of "
                                    "Japanese voices.")

    def _apply(self):
        c = self.cfg
        c.hotkey = self.hotkey.text().strip()
        c.tesseract_cmd = self.tesseract.text().strip()
        c.ocr_min_confidence = self.min_conf.value()
        c.translator = self.translator.currentData()
        c.voice = self.voice.currentData() or c.voice
        c.hearing_voices = [self.hearing.item(i).data(Qt.ItemDataRole.UserRole)
                            for i in range(self.hearing.count())
                            if self.hearing.item(i).checkState() == Qt.CheckState.Checked]
        c.dictionary = self.dictionary.currentData()
        c.theme = self.theme.currentData()
        c.lookup_key = self.lookup_key.currentData()
        c.anthropic_api_key = self.api_key.text().strip()
        c.story_model = self.story_model.text().strip() or "claude-haiku-5-5"
        c.japanese_font_size = self.ja_size.value()
        c.english_font_size = self.en_size.value()
        c.sections = [k for k in ALL_SECTIONS if self.section_boxes[k].isChecked()]
        c.save()
        log.info("Settings saved (API key %s)", "set" if c.anthropic_api_key else "not set")
        self.applied.emit()

    def _save_and_close(self):
        self._apply()
        self.accept()

    def sync_sections(self):
        for k, cb in self.section_boxes.items():
            cb.setChecked(k in self.cfg.sections)
