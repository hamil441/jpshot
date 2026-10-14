"""Screenshot panel: mouse wheel zooms around the cursor, drag to pan, double-click to fit."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ImageView(QGraphicsView):
    MIN_ZOOM, MAX_ZOOM = 0.05, 20.0

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._item)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(120)
        self.setToolTip("Scroll to zoom · drag to move · double-click to fit")
        self._fit = True   # keep fitting on resize until the user zooms

    def set_pixmap(self, pm: QPixmap | None):
        self._item.setPixmap(pm if pm is not None else QPixmap())
        self.scene().setSceneRect(self._item.boundingRect())
        self.fit()

    def fit(self):
        self._fit = True
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        if self._item.pixmap().isNull():
            return
        steps = e.angleDelta().y() / 120
        factor = 1.2 ** steps
        zoom = self.transform().m11() * factor
        if not (self.MIN_ZOOM <= zoom <= self.MAX_ZOOM):
            return
        self._fit = False
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()
