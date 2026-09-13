"""Target and tracking controls."""

from PySide6.QtCore import Qt, Signal
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
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        eyebrow = QLabel("TRACKING")
        eyebrow.setProperty("role", "eyebrow")
        title = QLabel("目标与云台控制")
        title.setProperty("role", "section-title")
        subtitle = QLabel("在画面中点击人员，再开始自动追踪")
        subtitle.setProperty("role", "section-subtitle")
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        summary = QFrame()
        summary.setProperty("role", "inset")
        grid = QGridLayout()
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
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
            label_widget = QLabel(label)
            label_widget.setProperty("role", "metric-label")
            widget.setProperty("role", "metric-value")
            widget.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            grid.addWidget(label_widget, row, 0)
            grid.addWidget(widget, row, 1)
        summary.setLayout(grid)
        layout.addWidget(summary)

        self.start_button = QPushButton("开始追踪")
        self.start_button.setProperty("kind", "primary")
        self.start_button.setMinimumHeight(42)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_requested)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("停止追踪")
        self.stop_button.setProperty("kind", "danger")
        self.stop_button.setMinimumHeight(42)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

        manual_card = QFrame()
        manual_card.setProperty("role", "inset")
        manual_layout = QVBoxLayout(manual_card)
        manual_layout.setContentsMargins(12, 10, 12, 10)
        manual_layout.setSpacing(4)
        manual_title = QLabel("手动微调")
        manual_title.setProperty("role", "metric-value")
        manual_layout.addWidget(manual_title)
        self.manual_label = QLabel(
            "停止追踪后可按住：\nW 向上    S 向下\nA 向左    D 向右"
        )
        self.manual_label.setProperty("role", "helper")
        manual_layout.addWidget(self.manual_label)
        layout.addWidget(manual_card)

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
