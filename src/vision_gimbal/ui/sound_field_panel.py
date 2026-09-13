"""Separate view for the camera image with its latest relative field overlay."""

from __future__ import annotations

import cv2
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..domain.spatial_field import SpatialFieldSnapshot
from .overlay_renderer import render_sound_field_overlay
from .video_transform import aspect_fit_rect


class SoundFieldCanvas(QWidget):
    """Render only a camera frame plus field overlay; it has no input controls."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("soundFieldCanvas")
        self._spatial: SpatialFieldSnapshot | None = None
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(500, 281)

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
        painter.fillRect(self.rect(), QColor("#07101e"))
        if self._pixmap is None:
            painter.setPen(QColor("#a8b9cf"))
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
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)
        title = QLabel("实时声场模拟")
        title.setProperty("role", "section-title")
        layout.addWidget(title)
        subtitle = QLabel("实时声场模拟")
        subtitle.setProperty("role", "section-subtitle")
        layout.addWidget(subtitle)

        canvas_frame = QWidget()
        canvas_frame.setProperty("card", True)
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(1, 1, 1, 1)
        self.canvas = SoundFieldCanvas()
        canvas_layout.addWidget(self.canvas)
        layout.addWidget(canvas_frame, 1)

    def set_spatial_field_snapshot(self, snapshot: SpatialFieldSnapshot) -> None:
        self.canvas.set_spatial_field_snapshot(snapshot)
