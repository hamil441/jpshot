"""Capture history: every capture's screenshot, text, translation and words, plus a browser window."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

log = logging.getLogger("jpshot.history")


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "jpshot" / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Capture:
    id: str
    time: float
    language: str          # language of the screenshot text
    source: str            # OCR text
    japanese: str
    english: str
    difficulty: str = ""
    words: list = field(default_factory=list)   # dictionary forms of the content words
    image: str = ""        # file name inside the history folder

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.time))


class History:
    def __init__(self):
        self.dir = data_dir()
        self.index = self.dir / "index.jsonl"

    def add(self, cap: Capture, pixmap: QPixmap | None) -> None:
        if pixmap is not None and not pixmap.isNull():
            cap.image = f"{cap.id}.png"
            pixmap.save(str(self.dir / cap.image), "PNG")
        with self.index.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(cap), ensure_ascii=False) + "\n")
        log.info("Saved capture %s to history", cap.id)

    # -- the last capture (always kept, even with History switched off) ----------
    def save_last(self, cap: Capture, pixmap: QPixmap | None) -> None:
        try:
            img = ""
            if pixmap is not None and not pixmap.isNull():
                img = "last.png"
                pixmap.save(str(self.dir / img), "PNG")
            d = asdict(cap)
            d["image"] = img
            (self.dir / "last.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            log.debug("Saved last capture %s", cap.id)
        except Exception:  # noqa: BLE001
            log.exception("Could not save the last capture")

    def last(self) -> tuple[Capture, QPixmap | None] | None:
        """The most recent capture (last.json, else the newest history entry), or None."""
        p = self.dir / "last.json"
        if p.exists():
            try:
                cap = Capture(**json.loads(p.read_text(encoding="utf-8")))
                return cap, self.pixmap(cap)
            except Exception:  # noqa: BLE001
                log.warning("last.json is unreadable; ignoring it")
        caps = self.all()
        return (caps[0], self.pixmap(caps[0])) if caps else None

    def all(self) -> list[Capture]:
        out = []
        if self.index.exists():
            for line in self.index.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(Capture(**json.loads(line)))
                except Exception:  # noqa: BLE001
                    continue
        return list(reversed(out))

    def pixmap(self, cap: Capture) -> QPixmap | None:
        if cap.image and (self.dir / cap.image).exists():
            return QPixmap(str(self.dir / cap.image))
        return None

    def remove(self, cap_id: str) -> None:
        keep = [c for c in reversed(self.all()) if c.id != cap_id]
        with self.index.open("w", encoding="utf-8") as f:
            for c in keep:
                f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
        try:
            (self.dir / f"{cap_id}.png").unlink()
        except FileNotFoundError:
            pass

    def frequent_unknown(self, is_known, min_count: int = 2) -> list[tuple[str, int, str]]:
        """Words seen in several captures that you don't know yet: (word, count, example sentence)."""
        counts: Counter = Counter()
        example: dict[str, str] = {}
        for c in self.all():
            for w in set(c.words):
                if not is_known(w):
                    counts[w] += 1
                    example.setdefault(w, c.japanese)
        return [(w, n, example[w]) for w, n in counts.most_common() if n >= min_count]


class HistoryWindow(QWidget):
    open_capture = Signal(object)     # Capture
    mark_known = Signal(str)

    def __init__(self, history: History, is_known):
        super().__init__(None, Qt.WindowType.Window)
        self.history = history
        self.is_known = is_known
        self.setWindowTitle("JPShot history")
        self.resize(720, 640)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Japanese, English or words…")
        self.search.textChanged.connect(self.refresh)
        self.list = QListWidget()
        self.list.setIconSize(QSize(120, 68))
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(lambda it: self.open_capture.emit(it.data(Qt.ItemDataRole.UserRole)))
        delete = QPushButton("Delete selected")
        delete.clicked.connect(self._delete)
        caps = QWidget()
        cl = QVBoxLayout(caps)
        cl.addWidget(self.search)
        cl.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("<span style='color:gray'>Double-click a capture to open it again</span>"))
        row.addStretch()
        row.addWidget(delete)
        cl.addLayout(row)

        self.words = QListWidget()
        self.words.setWordWrap(True)
        known_btn = QPushButton("Mark selected as known")
        known_btn.clicked.connect(self._mark_known)
        words = QWidget()
        wl = QVBoxLayout(words)
        wl.addWidget(QLabel("Words you keep running into but haven't marked known — the best ones to learn next:"))
        wl.addWidget(self.words, 1)
        wl.addWidget(known_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.tabs = QTabWidget()
        self.tabs.addTab(caps, "Captures")
        self.tabs.addTab(words, "Words you keep seeing")
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        self.refresh()

    def refresh(self):
        if self.tabs.currentIndex() == 1:
            self.words.clear()
            for w, n, ex in self.history.frequent_unknown(self.is_known):
                it = QListWidgetItem(f"{w}   ×{n}\n    {ex[:80]}")
                it.setData(Qt.ItemDataRole.UserRole, w)
                self.words.addItem(it)
            if not self.words.count():
                self.words.addItem("Nothing yet — words show up here after you've seen them in two or more captures.")
            return
        q = self.search.text().strip().lower()
        self.list.clear()
        for c in self.history.all():
            hay = f"{c.japanese}\n{c.english}\n{' '.join(c.words)}".lower()
            if q and q not in hay:
                continue
            text = f"{c.when}  {c.difficulty}\n{c.japanese[:90]}\n{c.english[:90]}"
            it = QListWidgetItem(text)
            pm = self.history.pixmap(c)
            if pm is not None:
                it.setIcon(QIcon(pm.scaled(240, 136, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)))
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.list.addItem(it)

    def _delete(self):
        for it in self.list.selectedItems():
            c = it.data(Qt.ItemDataRole.UserRole)
            if c:
                self.history.remove(c.id)
        self.refresh()

    def _mark_known(self):
        for it in self.words.selectedItems():
            w = it.data(Qt.ItemDataRole.UserRole)
            if w:
                self.mark_known.emit(w)
        self.refresh()
