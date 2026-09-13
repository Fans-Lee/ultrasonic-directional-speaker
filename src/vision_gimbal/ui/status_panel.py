"""Connection and user-message panel."""

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .view_models import MainWindowViewModel


class StatusPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(9)

        eyebrow = QLabel("SYSTEM")
        eyebrow.setProperty("role", "eyebrow")
        title = QLabel("设备状态")
        title.setProperty("role", "section-title")
        layout.addWidget(eyebrow)
        layout.addWidget(title)

        status_card = QFrame()
        status_card.setProperty("role", "inset")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)
        self.serial_label = QLabel("串口状态：-")
        self.serial_label.setProperty("role", "status")
        self.serial_detail = QLabel("")
        self.serial_detail.setWordWrap(True)
        self.serial_detail.setProperty("role", "helper")
        status_layout.addWidget(self.serial_label)
        status_layout.addWidget(self.serial_detail)

        self.message_label = QLabel("正在初始化…")
        self.message_label.setWordWrap(True)
        self.message_label.setProperty("role", "message")
        self.message_label.setProperty("error", False)
        layout.addWidget(status_card)
        layout.addWidget(self.message_label)

    def apply(self, view: MainWindowViewModel) -> None:
        self.serial_label.setText(f"串口状态：{view.serial_text}")
        self.serial_detail.setText(view.serial_detail)
        self.message_label.setText(view.message)

    def show_error(self, message: str) -> None:
        self.message_label.setText(f"错误：{message}")
        self.message_label.setProperty("error", True)
        style = self.message_label.style()
        style.unpolish(self.message_label)
        style.polish(self.message_label)
