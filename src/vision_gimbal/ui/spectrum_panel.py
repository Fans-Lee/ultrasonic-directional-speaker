"""Qt widgets for the rolling transmitted-audio spectrogram."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..audio.spectrum import AudioSpectrumSnapshot


def _build_palette() -> np.ndarray:
    """Build a compact magma-like lookup table without a plotting backend."""
    stops = np.array(
        [
            (0, 0, 4),
            (28, 16, 68),
            (79, 18, 123),
            (129, 37, 129),
            (181, 54, 122),
            (229, 80, 100),
            (251, 135, 97),
            (254, 194, 135),
            (252, 253, 191),
        ],
        dtype=np.float32,
    )
    positions = np.linspace(0.0, 1.0, stops.shape[0])
    samples = np.linspace(0.0, 1.0, 256)
    channels = [
        np.interp(samples, positions, stops[:, index]) for index in range(3)
    ]
    return np.column_stack(channels).astype(np.uint8)


_PALETTE = _build_palette()
_BACKGROUND = QColor(3, 7, 18)
_FOREGROUND = QColor(203, 213, 225)
_BORDER = QColor(71, 85, 105)


class SpectrumCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("spectrumCanvas")
        self._snapshot: AudioSpectrumSnapshot | None = None
        self._image: QImage | None = None
        self._message = "启动麦克风链路后显示发送音频频谱"
        self.setMinimumSize(500, 170)

    def apply(self, snapshot: AudioSpectrumSnapshot) -> None:
        self._snapshot = snapshot
        levels = snapshot.levels_dbfs
        valid = np.isfinite(levels)
        if not snapshot.active:
            self._image = None
            self._message = "启动麦克风链路后显示发送音频频谱"
        elif not np.any(valid):
            self._image = None
            self._message = "正在积累第一个分析窗口…"
        else:
            span = snapshot.max_dbfs - snapshot.min_dbfs
            normalized = np.clip(
                (levels - snapshot.min_dbfs) / span, 0.0, 1.0
            )
            indexes = np.nan_to_num(normalized, nan=0.0)
            indexes = np.rint(indexes * 255.0).astype(np.uint8)
            rgb = _PALETTE[indexes]
            rgb[~valid] = (3, 7, 18)
            rgb = np.ascontiguousarray(np.flipud(rgb))
            height, width = rgb.shape[:2]
            self._image = QImage(
                rgb.data,
                width,
                height,
                rgb.strides[0],
                QImage.Format.Format_RGB888,
            ).copy()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BACKGROUND)
        plot = QRectF(
            52.0,
            8.0,
            max(1.0, self.width() - 110.0),
            max(1.0, self.height() - 38.0),
        )
        painter.setPen(QPen(_BORDER, 1.0))
        painter.drawRect(plot)

        if self._image is None:
            painter.setPen(_FOREGROUND)
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._message)
        else:
            painter.drawImage(plot, self._image)
            painter.setPen(QPen(_BORDER, 1.0))
            painter.drawRect(plot)

        snapshot = self._snapshot
        if snapshot is None:
            return
        painter.setPen(_FOREGROUND)
        nyquist = snapshot.sample_rate / 2.0
        painter.drawText(
            QRectF(0.0, plot.top() - 7.0, 46.0, 18.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{nyquist / 1000.0:g} kHz",
        )
        painter.drawText(
            QRectF(0.0, plot.center().y() - 9.0, 46.0, 18.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{nyquist / 2000.0:g} kHz",
        )
        painter.drawText(
            QRectF(0.0, plot.bottom() - 10.0, 46.0, 18.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "0 Hz",
        )
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 3.0, 70.0, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"-{snapshot.history_s:g} s",
        )
        painter.drawText(
            QRectF(plot.right() - 70.0, plot.bottom() + 3.0, 70.0, 20.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "现在",
        )

        bar = QRectF(plot.right() + 12.0, plot.top(), 10.0, plot.height())
        segments = 64
        for index in range(segments):
            color_index = round(255.0 * (1.0 - index / (segments - 1)))
            top = bar.top() + bar.height() * index / segments
            bottom = bar.top() + bar.height() * (index + 1) / segments
            painter.fillRect(
                QRectF(bar.left(), top, bar.width(), bottom - top + 0.5),
                QColor(*(int(value) for value in _PALETTE[color_index])),
            )
        painter.setPen(QPen(_BORDER, 1.0))
        painter.drawRect(bar)
        painter.setPen(_FOREGROUND)
        painter.drawText(
            QRectF(bar.right() + 4.0, bar.top() - 7.0, 34.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{snapshot.max_dbfs:g}",
        )
        painter.drawText(
            QRectF(bar.right() + 4.0, bar.bottom() - 10.0, 34.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{snapshot.min_dbfs:g}",
        )


class SpectrumPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        title = QLabel("实时发送频谱（dBFS）")
        title.setProperty("role", "section-title")
        self.status = QLabel("等待麦克风链路")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status.setProperty("role", "helper")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status)
        layout.addLayout(header)

        canvas_frame = QWidget()
        canvas_frame.setProperty("card", True)
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(1, 1, 1, 1)
        self.canvas = SpectrumCanvas()
        canvas_layout.addWidget(self.canvas)
        layout.addWidget(canvas_frame, 1)

    def apply(self, snapshot: AudioSpectrumSnapshot) -> None:
        self.canvas.apply(snapshot)
        if not snapshot.active:
            self.status.setText("等待麦克风链路")
            return
        if snapshot.latest_peak_dbfs is None:
            self.status.setText("正在分析…")
            return
        detail = (
            f"{snapshot.sample_rate / 1000.0:g} kHz · "
            f"{snapshot.window_ms:g} ms 窗 · "
            f"峰值 {snapshot.latest_peak_dbfs:.1f} dBFS"
        )
        if snapshot.dropped_blocks:
            detail += f" · 分析丢块 {snapshot.dropped_blocks}"
        self.status.setText(detail)
