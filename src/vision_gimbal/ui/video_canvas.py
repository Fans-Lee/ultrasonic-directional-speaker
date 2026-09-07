"""Aspect-fitted video widget with track selection."""

import cv2
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

from ..application.vision_service import DisplayFrame
from ..domain.state import UiSnapshot
from .overlay_renderer import render_overlay
from .video_transform import aspect_fit_rect, select_track_at


class VideoCanvas(QWidget):
    target_selected = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._display_frame = None
        self._state = None
        self._pixmap = None
        self.setMinimumSize(640, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setStyleSheet("background: #111827;")

    def set_display_frame(self, display_frame: DisplayFrame) -> None:
        self._display_frame = display_frame
        self._rebuild_pixmap()

    def set_state(self, state: UiSnapshot) -> None:
        self._state = state
        if self._display_frame is not None:
            self._rebuild_pixmap()

    def _rebuild_pixmap(self) -> None:
        display = self._display_frame
        if display is None:
            return
        annotated = render_overlay(
            display.image,
            display.snapshot,
            self._state,
        )
        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
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
                self.rect(), Qt.AlignmentFlag.AlignCenter, "等待摄像头画面…"
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._display_frame is None:
            return super().mousePressEvent(event)
        snapshot = self._display_frame.snapshot
        point = event.position()
        track_id = select_track_at(
            (point.x(), point.y()),
            snapshot.frame_size,
            (self.width(), self.height()),
            snapshot.tracks,
        )
        if track_id is not None:
            self.target_selected.emit(track_id, snapshot.frame_id)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
