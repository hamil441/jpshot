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
    activated = Signal(object)         # this overlay got a click (multi-monitor: clear the others)

    HANDLE = 9       # handle square size (px)
    MIN = 6          # smallest usable selection

    def __init__(self, screen, shot: QPixmap):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.screen_ = screen
        self.shot = shot
        self.sel: QRect | None = None      # current selection (widget coordinates)
        self.mode = ""                     # "" | "new" | "move" | handle name ("tl", "t", "tr", …)
        self.press: QPoint | None = None
        self.start_sel: QRect | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def show_on_screen(self):
        try:
            self.setScreen(self.screen_)
        except AttributeError:  # older Qt
            pass
        self.setGeometry(self.screen_.geometry())
        self.showFullScreen()

    # -- geometry helpers -------------------------------------------------
    def _to_pixels(self, r: QRect) -> QRect:
        sx = self.shot.width() / max(1, self.width())
        sy = self.shot.height() / max(1, self.height())
        return QRect(round(r.x() * sx), round(r.y() * sy), round(r.width() * sx), round(r.height() * sy))

    def _handles(self) -> dict[str, QRect]:
        if not self.sel:
            return {}
        r, h = self.sel, self.HANDLE
        xs = {"l": r.left(), "c": r.center().x(), "r": r.right()}
        ys = {"t": r.top(), "m": r.center().y(), "b": r.bottom()}
        names = {("l", "t"): "tl", ("c", "t"): "t", ("r", "t"): "tr", ("l", "m"): "l", ("r", "m"): "r",
                 ("l", "b"): "bl", ("c", "b"): "b", ("r", "b"): "br"}
        return {n: QRect(xs[x] - h // 2, ys[y] - h // 2, h, h) for (x, y), n in names.items()}

    def _hit(self, pos: QPoint) -> str:
        for name, r in self._handles().items():
            if r.adjusted(-4, -4, 4, 4).contains(pos):
                return name
        if self.sel and self.sel.contains(pos):
            return "move"
        return ""

    CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
               "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
               "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
               "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
               "move": Qt.CursorShape.SizeAllCursor}

    def _clamp(self, r: QRect) -> QRect:
        return r.intersected(self.rect())

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 115))
        sel = self.sel
        f = QFont(self.font())
        if sel and sel.width() > 0 and sel.height() > 0:
            p.drawPixmap(sel, self.shot, self._to_pixels(sel))
            p.setPen(QPen(ACCENT, 2))
            p.drawRect(sel)
            if not self.mode or self.mode != "new":
                p.setPen(QPen(Qt.GlobalColor.white, 1))
                for r in self._handles().values():
                    p.fillRect(r, ACCENT)
                    p.drawRect(r)
            label = f"{sel.width()} × {sel.height()}"
            f.setPointSize(10)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(label) + 12
            box = QRect(sel.left(), sel.top() - 26 if sel.top() > 30 else sel.bottom() + 6, tw, 20)
            p.fillRect(box, ACCENT)
            p.setPen(Qt.GlobalColor.white)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            if not self.mode:
                hint = "Enter = capture · drag handles to resize · drag inside to move · Esc = cancel"
                hw = p.fontMetrics().horizontalAdvance(hint) + 16
                y = sel.bottom() + 30 if sel.bottom() + 54 < self.height() else sel.top() - 50
                hb = QRect(max(4, min(sel.left(), self.width() - hw - 4)), max(4, y), hw, 20)
                p.fillRect(hb, QColor(0, 0, 0, 170))
                p.drawText(hb, Qt.AlignmentFlag.AlignCenter, hint)
        elif self.geometry().contains(QCursor.pos()):
            f.setPointSize(14)
            p.setFont(f)
            p.setPen(Qt.GlobalColor.white)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Drag around the text  ·  adjust, then Enter  ·  Esc or right-click to cancel")

    # -- input ------------------------------------------------------------
    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        if e.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.activateWindow()
        self.setFocus()
        self.activated.emit(self)
        hit = self._hit(pos)
        self.press, self.start_sel = pos, QRect(self.sel) if self.sel else None
        if hit:
            self.mode = hit
        else:   # start a new selection
            self.mode = "new"
            self.sel = QRect(pos, pos)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if not self.mode:
            hit = self._hit(pos)
            self.setCursor(self.CURSORS.get(hit, Qt.CursorShape.CrossCursor))
            self.update()
            return
        if self.mode == "new":
            self.sel = QRect(self.press, pos).normalized()
        elif self.mode == "move" and self.start_sel:
            r = self.start_sel.translated(pos - self.press)
            r.moveLeft(max(0, min(r.left(), self.width() - r.width())))
            r.moveTop(max(0, min(r.top(), self.height() - r.height())))
            self.sel = r
        elif self.start_sel:
            r = QRect(self.start_sel)
            d = pos - self.press
            if "l" in self.mode:
                r.setLeft(r.left() + d.x())
            if "r" in self.mode:
                r.setRight(r.right() + d.x())
            if self.mode in ("t", "tl", "tr"):
                r.setTop(r.top() + d.y())
            if self.mode in ("b", "bl", "br"):
                r.setBottom(r.bottom() + d.y())
            self.sel = self._clamp(r.normalized())
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.mode:
            return
        self.mode = ""
        if self.sel is None or self.sel.width() < self.MIN or self.sel.height() < self.MIN:
            log.debug("Selection too small (%s)", self.sel)
            self.sel = self.start_sel if self.start_sel and self.start_sel.width() >= self.MIN else None
        self.setCursor(self.CURSORS.get(self._hit(e.position().toPoint()), Qt.CursorShape.CrossCursor))
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.sel and self.sel.contains(e.position().toPoint()):
            self._finish()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish()
        elif self.sel and k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 10 if e.modifiers() & Qt.KeyboardModifier.ControlModifier else 1
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0)
            r = QRect(self.sel)
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:   # resize from the bottom-right
                r.setWidth(max(self.MIN, r.width() + dx))
                r.setHeight(max(self.MIN, r.height() + dy))
            else:
                r.translate(dx, dy)
            self.sel = self._clamp(r)
            self.update()

    def _finish(self):
        sel = self.sel
        if sel is None or sel.width() < self.MIN or sel.height() < self.MIN:
            return
        px = self._to_pixels(sel)
        crop = self.shot.copy(px)
        crop.setDevicePixelRatio(1.0)
        glob = QRect(self.mapToGlobal(sel.topLeft()), sel.size())
        log.info("Selected %dx%d px on screen %r", px.width(), px.height(), self.screen_.name())
        self.selected.emit(crop, glob)


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
            ov.activated.connect(self._activated)
            self.overlays.append(ov)
        under = QGuiApplication.screenAt(QCursor.pos())
        for ov in self.overlays:
            ov.show_on_screen()
        for ov in self.overlays:
            ov.raise_()  # above the (still open) result window
        for ov in self.overlays:
            if ov.screen_ is under:
                ov.raise_()
                ov.activateWindow()
                ov.setFocus()

    def _activated(self, active):
        for ov in self.overlays:
            if ov is not active and ov.sel is not None:
                ov.sel = None
                ov.update()

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
