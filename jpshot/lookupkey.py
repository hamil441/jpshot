"""The key held to show the word popup (configurable: shift, ctrl, alt, meta)."""
from __future__ import annotations

from PySide6.QtCore import Qt

KEYS = {
    "shift": (Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Shift, "Shift"),
    "ctrl": (Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control, "Ctrl"),
    "alt": (Qt.KeyboardModifier.AltModifier, Qt.Key.Key_Alt, "Alt"),
    "meta": (Qt.KeyboardModifier.MetaModifier, Qt.Key.Key_Meta, "Super"),
}
_current = "shift"


def set_key(name: str) -> None:
    global _current
    _current = name if name in KEYS else "shift"


def modifier():
    return KEYS[_current][0]


def key():
    return KEYS[_current][1]


def name() -> str:
    return KEYS[_current][2]
