"""Separate view for the camera image with its latest relative field overlay."""

from __future__ import annotations

import cv2
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..domain.spatial_field import SpatialFieldSnapshot
from .overlay_renderer import render_sound_field_overlay
from .video_transform import aspect_fit_rect


class SoundFieldCanvas(QWidget):
    """Render only a camera frame plus field overlay; it has no input controls."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._spatial: SpatialFieldSnapshot | None = None
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(500, 281)
        self.setStyleSheet("background: #111827;")

    def set_spatial_field_snapshot(self, snapshot: SpatialFieldSnapshot) -> None:
        self._spatial = snapshot
        self._rebuild_pixmap()

    def _rebuild_pixmap(self) -> None:
        if self._spatial is None or self._spatial.source_frame_bgr is None:
            return
        overlay = render_sound_field_overlay(
            self._spatial.source_frame_bgr,
            self._spatial,
        )
        rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(
            rgb.data,
            width,
            height,
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._pixmap is None:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "等待声场分析…",
            )
            return
        source = (self._pixmap.width(), self._pixmap.height())
        target = aspect_fit_rect(source, (self.width(), self.height()))
        painter.drawPixmap(
            QRect(
                round(target.x),
                round(target.y),
                round(target.width),
                round(target.height),
            ),
            self._pixmap,
        )


class SoundFieldPanel(QWidget):
    """Standalone acoustic image panel, separate from the tracking video."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("相对声场叠加画面")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)
        self.canvas = SoundFieldCanvas()
        layout.addWidget(self.canvas, 1)

    def set_spatial_field_snapshot(self, snapshot: SpatialFieldSnapshot) -> None:
        self.canvas.set_spatial_field_snapshot(snapshot)
