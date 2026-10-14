"""Animated stroke order from KanjiVG data (strokes appear one by one, in each part's color)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG = "http://www.w3.org/2000/svg"
_TOKEN = re.compile(r"[MmLlCcSsQqTtHhVvZz]|-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def parse_path(d: str) -> list[tuple]:
    """SVG path data -> absolute segments: ("M", x, y) ("L", x, y) ("C", x1, y1, x2, y2, x, y)."""
    toks = _TOKEN.findall(d)
    out: list[tuple] = []
    i, cmd = 0, None
    cx = cy = sx = sy = 0.0
    last_c2 = None   # last cubic control point, for S

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                out.append(("L", sx, sy))
                cx, cy, last_c2 = sx, sy, None
                continue
        if cmd is None:
            break
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (cx, cy) if rel else (0.0, 0.0)
        if c == "M":
            cx, cy = ox + num(), oy + num()
            sx, sy = cx, cy
            out.append(("M", cx, cy))
            cmd = "l" if rel else "L"     # further pairs are line-tos
            last_c2 = None
        elif c == "L":
            cx, cy = ox + num(), oy + num()
            out.append(("L", cx, cy))
            last_c2 = None
        elif c == "H":
            cx = (cx if rel else 0.0) + num()
            out.append(("L", cx, cy))
            last_c2 = None
        elif c == "V":
            cy = (cy if rel else 0.0) + num()
            out.append(("L", cx, cy))
            last_c2 = None
        elif c == "C":
            x1, y1, x2, y2, x, y = (ox + num(), oy + num(), ox + num(), oy + num(), ox + num(), oy + num())
            out.append(("C", x1, y1, x2, y2, x, y))
            cx, cy, last_c2 = x, y, (x2, y2)
        elif c == "S":
            x1, y1 = (2 * cx - last_c2[0], 2 * cy - last_c2[1]) if last_c2 else (cx, cy)
            x2, y2, x, y = ox + num(), oy + num(), ox + num(), oy + num()
            out.append(("C", x1, y1, x2, y2, x, y))
            cx, cy, last_c2 = x, y, (x2, y2)
        elif c == "Q":
            qx, qy, x, y = ox + num(), oy + num(), ox + num(), oy + num()
            out.append(("C", cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy),
                        x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y), x, y))
            cx, cy, last_c2 = x, y, None
        else:   # T and anything unexpected: treat as line to the end point
            cx, cy = ox + num(), oy + num()
            out.append(("L", cx, cy))
            last_c2 = None
    return out


def strokes_from_svg(svg_text: str) -> list[tuple[str, str]]:
    """[(path data, color)] in stroke order, from a (colored) KanjiVG drawing."""
    svg_text = re.sub(r"(?s)<!DOCTYPE.*?\]>", "", svg_text)
    if "xmlns:kvg" not in svg_text.split("<svg", 1)[-1].split(">", 1)[0]:
        svg_text = svg_text.replace("<svg ", '<svg xmlns:kvg="http://kanjivg.tagaini.net" ', 1)
    root = ET.fromstring(svg_text)
    out = []
    for p in root.iter(f"{{{SVG}}}path"):
        d = p.get("d")
        if not d:
            continue
        m = re.search(r"stroke:\s*(#[0-9a-fA-F]{3,8})", p.get("style", ""))
        out.append((d, m.group(1) if m else ""))
    return out


# --- Qt window -----------------------------------------------------------------
def _qt_window():
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
    from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

    def to_qpath(segs) -> QPainterPath:
        path = QPainterPath()
        for s in segs:
            if s[0] == "M":
                path.moveTo(s[1], s[2])
            elif s[0] == "L":
                path.lineTo(s[1], s[2])
            else:
                path.cubicTo(s[1], s[2], s[3], s[4], s[5], s[6])
        return path

    class Canvas(QWidget):
        def __init__(self, strokes):
            super().__init__()
            self.paths = [(to_qpath(parse_path(d)), QColor(c) if c else None) for d, c in strokes]
            self.done = 0          # strokes fully drawn
            self.t = 0.0           # progress of the current stroke (0..1)
            self.numbers = True
            self.setMinimumSize(260, 260)

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pal = self.palette()
            p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base))
            side = min(self.width(), self.height()) - 16
            p.translate((self.width() - side) / 2, (self.height() - side) / 2)
            p.scale(side / 109, side / 109)
            guide = QColor(pal.color(QPalette.ColorRole.Mid))
            grid = QPen(guide, 0.3, Qt.PenStyle.DashLine)
            p.setPen(grid)
            p.drawLine(QPointF(54.5, 0), QPointF(54.5, 109))
            p.drawLine(QPointF(0, 54.5), QPointF(109, 54.5))
            text = pal.color(QPalette.ColorRole.Text)
            faint = QColor(text)
            faint.setAlpha(35)
            for path, _c in self.paths:          # the whole character, faintly
                p.setPen(QPen(faint, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
            for i, (path, col) in enumerate(self.paths[:self.done + 1]):
                pen = QPen(col or text, 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                if i < self.done:
                    p.drawPath(path)
                elif self.t > 0:
                    pts = [path.pointAtPercent(min(1.0, k / 40 * self.t)) for k in range(41)]
                    for a, b in zip(pts, pts[1:]):
                        p.drawLine(a, b)
            if self.numbers:
                f = QFont(self.font())
                f.setPixelSize(7)
                p.setFont(f)
                for i, (path, col) in enumerate(self.paths[:self.done + (1 if self.t > 0 else 0)]):
                    start = path.pointAtPercent(0)
                    p.setPen(col or text)
                    p.drawText(QRectF(start.x() - 9, start.y() - 9, 8, 8), Qt.AlignmentFlag.AlignCenter, str(i + 1))

    class StrokeOrderWindow(QWidget):
        def __init__(self, char: str, strokes, keyword: str = ""):
            super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
            self.setWindowTitle(f"{char} — stroke order")
            self.canvas = Canvas(strokes)
            title = QLabel(f"<span style='font-size:16pt'>{char}</span>  <b>{keyword}</b>  "
                           f"<span style='color:gray'>{len(strokes)} strokes</span>")
            replay = QPushButton("▶ Replay")
            replay.clicked.connect(self.replay)
            step = QPushButton("Next stroke ⏭")
            step.clicked.connect(self.step)
            nums = QCheckBox("Numbers")
            nums.setChecked(True)
            nums.toggled.connect(lambda on: (setattr(self.canvas, "numbers", on), self.canvas.update()))
            self.speed = QSlider(Qt.Orientation.Horizontal)
            self.speed.setRange(1, 10)
            self.speed.setValue(5)
            self.speed.setToolTip("Animation speed")
            row = QHBoxLayout()
            for w in (replay, step, nums):
                row.addWidget(w)
            row.addWidget(QLabel("speed"))
            row.addWidget(self.speed, 1)
            lay = QVBoxLayout(self)
            lay.addWidget(title)
            lay.addWidget(self.canvas, 1)
            lay.addLayout(row)
            self.resize(380, 460)
            self.timer = QTimer(self, interval=16)
            self.timer.timeout.connect(self._tick)
            self.pause = 0
            self.replay()

        def replay(self):
            self.canvas.done, self.canvas.t, self.pause = 0, 0.0, 0
            self.timer.start()

        def step(self):
            self.timer.stop()
            c = self.canvas
            if c.t > 0:
                c.done, c.t = c.done + 1, 0.0
            if c.done >= len(c.paths):
                c.done, c.t = 0, 0.0
            c.t = 1.0
            c.update()

        def _tick(self):
            c = self.canvas
            if c.done >= len(c.paths):
                self.timer.stop()
                return
            if self.pause > 0:
                self.pause -= 1
                return
            path = c.paths[c.done][0]
            length = max(10.0, path.length())
            c.t += 0.016 * self.speed.value() * 18 / length
            if c.t >= 1.0:
                c.done += 1
                c.t = 0.0
                self.pause = 8
            c.update()

    return StrokeOrderWindow


def open_window(char: str, svg_text: str, keyword: str = ""):
    cls = _qt_window()
    win = cls(char, strokes_from_svg(svg_text), keyword)
    win.show()
    return win
