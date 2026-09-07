"""Target and tracking controls."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .view_models import MainWindowViewModel


class ControlPanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("目标与控制")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        grid = QGridLayout()
        self.mode_value = QLabel("-")
        self.selected_value = QLabel("-")
        self.active_value = QLabel("-")
        self.target_status_value = QLabel("-")
        self.pose_value = QLabel("-")
        self.source_value = QLabel("-")
        rows = (
            ("模式", self.mode_value),
            ("选中目标", self.selected_value),
            ("活动目标", self.active_value),
            ("目标状态", self.target_status_value),
            ("指令角度", self.pose_value),
            ("控制来源", self.source_value),
        )
        for row, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)
        layout.addLayout(grid)

        self.start_button = QPushButton("开始追踪")
        self.start_button.setMinimumHeight(42)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_requested)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("停止追踪")
        self.stop_button.setMinimumHeight(42)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet(
            "QPushButton { background: #b91c1c; color: white; font-weight: 600; }"
            "QPushButton:disabled { background: #6b7280; }"
        )
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        self.manual_label = QLabel(
            "停止追踪后可按住：\nW 向上    S 向下\nA 向左    D 向右"
        )
        self.manual_label.setStyleSheet("padding: 8px; color: #d1d5db;")
        layout.addWidget(self.manual_label)
        layout.addStretch(1)

    def apply(self, view: MainWindowViewModel) -> None:
        self.mode_value.setText(view.mode_text)
        self.selected_value.setText(view.selected_target_text)
        self.active_value.setText(view.active_target_text)
        self.target_status_value.setText(view.target_status_text)
        self.pose_value.setText(view.pose_text)
        self.source_value.setText(view.control_source_text)
        self.start_button.setText(view.start_button_text)
        self.start_button.setEnabled(view.start_enabled)
        self.stop_button.setEnabled(view.stop_enabled)
        self.manual_label.setEnabled(view.manual_enabled)
