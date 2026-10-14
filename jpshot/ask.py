"""“Ask about this sentence”: a small tutor chat about the captured sentence (uses the story writer)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser,
                               QVBoxLayout)

from .workers import run_async

log = logging.getLogger("jpshot.ask")

PRESETS = [
    ("Explain it", "Explain this sentence for me: its structure, what each part does, and how it "
                   "gets to the English meaning."),
    ("Particles", "Explain each particle in this sentence and why it's used here rather than an alternative."),
    ("Nuance", "What's the tone, politeness level and nuance of this sentence? How would it sound to a "
               "native speaker, and how would you say it more politely or more casually?"),
    ("Word by word", "Break this sentence down word by word with readings and meanings, then put it "
                     "back together."),
]

SYSTEM = """You are a patient, precise Japanese tutor for an English-speaking learner.
The learner is reading this Japanese (captured from their screen):
{sentence}
English translation: {english}
Grammar points detected: {patterns}

Answer the learner's questions about it. Be concise (usually under 180 words unless asked for more).
Give readings in hiragana in parentheses after kanji words the first time you use them. Use simple
markdown: **bold**, short bullet lists. Be accurate; if something is ambiguous or casual/slangy, say so."""


class AskDialog(QDialog):
    def __init__(self, kanji_db, sentence: str, english: str, patterns: list[str], parent=None):
        super().__init__(parent)
        self.db = kanji_db
        self.system = SYSTEM.format(sentence=sentence, english=english or "(not available)",
                                    patterns=", ".join(patterns) or "none")
        self.messages: list[dict] = []
        self.transcript = ""
        self.setWindowTitle("Ask about this sentence")
        self.resize(560, 620)

        head = QLabel(f"<span style='font-size:15pt'>{sentence}</span><br>"
                      f"<span style='color:gray'>{english}</span>")
        head.setWordWrap(True)
        head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        presets = QHBoxLayout()
        for label, q in PRESETS:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, text=q, lab=label: self.ask(text, lab))
            presets.addWidget(b)
        presets.addStretch()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask anything, e.g. “why が and not は here?”")
        self.input.returnPressed.connect(lambda: self.ask(self.input.text()))
        send = QPushButton("Ask")
        send.clicked.connect(lambda: self.ask(self.input.text()))
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(send)
        self.status = QLabel()
        self.status.setStyleSheet("color:gray")

        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addLayout(presets)
        lay.addWidget(self.view, 1)
        lay.addLayout(row)
        lay.addWidget(self.status)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        if not self.db.has_writer():
            self.view.setMarkdown("**No explanation writer is set up yet.**\n\nIn ⚙ Settings → *Explanations*, "
                                  "choose **Ollama** (free, runs on your computer: `sudo pacman -S ollama`, "
                                  "`ollama pull qwen2.5:7b`) or add an **Anthropic API key**.")
        else:
            self.ask(PRESETS[0][1], PRESETS[0][0])

    def ask(self, question: str, label: str = ""):
        question = question.strip()
        if not question:
            return
        self.input.clear()
        self.messages.append({"role": "user", "content": question})
        self.transcript += f"\n\n---\n\n**You:** {label or question}\n\n"
        self.view.setMarkdown(self.transcript + "_thinking…_")
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self.status.setText("Thinking…")
        log.info("Ask: %s", label or question)
        run_async(self.db.chat, list(self.messages), self.system, on_done=self._answer, on_error=self._failed)

    def _answer(self, text: str):
        self.messages.append({"role": "assistant", "content": text})
        self.transcript += text.strip()
        self.view.setMarkdown(self.transcript)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self.status.setText("")

    def _failed(self, msg: str):
        self.messages.pop()   # let them retry
        self.transcript += f"_Couldn't get an answer: {msg.split(': ', 1)[-1]}_"
        self.view.setMarkdown(self.transcript)
        self.status.setText("")
