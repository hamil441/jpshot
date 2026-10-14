"""Light / dark theme for the whole app (Fusion style + palette)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger("jpshot.theme")
ACCENT = "#e8556d"


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001  (Qt < 6.5)
        return False


def is_dark(theme: str) -> bool:
    return theme == "dark" or (theme == "system" and system_is_dark())


def _dark_palette() -> QPalette:
    p = QPalette()
    c = {
        QPalette.ColorRole.Window: "#1f2023",
        QPalette.ColorRole.WindowText: "#e7e7ea",
        QPalette.ColorRole.Base: "#2a2b2f",
        QPalette.ColorRole.AlternateBase: "#303136",
        QPalette.ColorRole.ToolTipBase: "#2a2b2f",
        QPalette.ColorRole.ToolTipText: "#e7e7ea",
        QPalette.ColorRole.PlaceholderText: "#8a8b90",
        QPalette.ColorRole.Text: "#e7e7ea",
        QPalette.ColorRole.Button: "#2c2d31",
        QPalette.ColorRole.ButtonText: "#e7e7ea",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Light: "#3a3b40",
        QPalette.ColorRole.Midlight: "#34353a",
        QPalette.ColorRole.Mid: "#46474d",
        QPalette.ColorRole.Dark: "#151618",
        QPalette.ColorRole.Shadow: "#000000",
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#ff8a9c",
    }
    for role, col in c.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6d6e73"))
    return p


def _light_palette(app: QApplication) -> QPalette:
    p = app.style().standardPalette()
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return p


def apply(theme: str) -> None:
    app = QApplication.instance()
    app.setStyle("Fusion")
    dark = is_dark(theme)
    app.setPalette(_dark_palette() if dark else _light_palette(app))
    # widgets with style sheets that reference palette(...) need re-parsing
    for w in app.allWidgets():
        ss = w.styleSheet()
        if ss:
            w.setStyleSheet("")
            w.setStyleSheet(ss)
    log.info("Theme: %s (%s)", theme, "dark" if dark else "light")
