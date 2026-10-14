"""Flameshot-style region selection: freeze every screen, drag a rectangle, get the cropped pixmap."""
from __future__ import annotations

import io
import logging

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

log = logging.getLogger("jpshot.capture")
ACCENT = QColor("#e8556d")


def pixmap_to_pil(pm: QPixmap) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGB")


class SelectionOverlay(QWidget):
    selected = Signal(QPixmap, QRect)  # cropped image, selection in global coordinates
    cancelled = Signal()

    def __init__(self, screen, shot: QPixmap):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.screen_ = screen
        self.shot = shot
        self.origin: QPoint | None = None
        self.current: QPoint | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def show_on_screen(self):
        try:
            self.setScreen(self.screen_)
        except AttributeError:  # older Qt
            pass
        self.setGeometry(self.screen_.geometry())
        self.showFullScreen()

    # -- geometry helpers -------------------------------------------------
    def _sel(self) -> QRect | None:
        if self.origin is None or self.current is None:
            return None
        return QRect(self.origin, self.current).normalized()

    def _to_pixels(self, r: QRect) -> QRect:
        sx = self.shot.width() / max(1, self.width())
        sy = self.shot.height() / max(1, self.height())
        return QRect(round(r.x() * sx), round(r.y() * sy), round(r.width() * sx), round(r.height() * sy))

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 115))
        sel = self._sel()
        if sel and sel.width() > 0 and sel.height() > 0:
            p.drawPixmap(sel, self.shot, self._to_pixels(sel))
            p.setPen(QPen(ACCENT, 2))
            p.drawRect(sel)
            label = f"{sel.width()} × {sel.height()}"
            f = QFont(self.font())
            f.setPointSize(10)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(label) + 12
            box = QRect(sel.left(), sel.top() - 24 if sel.top() > 28 else sel.bottom() + 4, tw, 20)
            p.fillRect(box, ACCENT)
            p.setPen(Qt.GlobalColor.white)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        elif self.geometry().contains(QCursor.pos()):
            f = QFont(self.font())
            f.setPointSize(14)
            p.setFont(f)
            p.setPen(Qt.GlobalColor.white)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Drag around the text  ·  Esc or right-click to cancel")

    # -- input ------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif e.button() == Qt.MouseButton.LeftButton:
            self.origin = self.current = e.position().toPoint()
            self.update()

    def mouseMoveEvent(self, e):
        if self.origin is not None:
            self.current = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.current = e.position().toPoint()
        sel = self._sel()
        if sel is None or sel.width() < 6 or sel.height() < 6:
            log.debug("Selection too small (%s); keep selecting", sel)
            self.origin = self.current = None
            self.update()
            return
        px = self._to_pixels(sel)
        crop = self.shot.copy(px)
        crop.setDevicePixelRatio(1.0)
        glob = QRect(self.mapToGlobal(sel.topLeft()), sel.size())
        log.info("Selected %dx%d px on screen %r", px.width(), px.height(), self.screen_.name())
        self.selected.emit(crop, glob)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class CaptureSession(QObject):
    selected = Signal(QPixmap, QRect)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.overlays: list[SelectionOverlay] = []
        screens = QGuiApplication.screens()
        shots = []
        for s in screens:
            pm = s.grabWindow(0)
            log.debug("Grabbed screen %r geometry=%s pixmap=%dx%d dpr=%.2f", s.name(), s.geometry(),
                      pm.width(), pm.height(), s.devicePixelRatio())
            if pm.isNull() or pm.width() == 0:
                log.error("Screen grab of %r returned an empty image. On Wayland, Qt cannot grab the "
                          "screen — run under X11/XWayland (QT_QPA_PLATFORM=xcb).", s.name())
            shots.append((s, pm))
        for s, pm in shots:
            ov = SelectionOverlay(s, pm)
            ov.selected.connect(self._done)
            ov.cancelled.connect(self._cancel)
            self.overlays.append(ov)
        under = QGuiApplication.screenAt(QCursor.pos())
        for ov in self.overlays:
            ov.show_on_screen()
        for ov in self.overlays:
            if ov.screen_ is under:
                ov.raise_()
                ov.activateWindow()
                ov.setFocus()

    def _close(self):
        for ov in self.overlays:
            ov.close()
        self.overlays.clear()

    def _done(self, pm, rect):
        self._close()
        self.selected.emit(pm, rect)

    def _cancel(self):
        log.info("Capture cancelled")
        self._close()
        self.cancelled.emit()
