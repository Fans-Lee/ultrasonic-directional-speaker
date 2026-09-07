"""Connection and user-message panel."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .view_models import MainWindowViewModel


class StatusPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.serial_label = QLabel("串口状态：-")
        self.serial_detail = QLabel("")
        self.message_label = QLabel("正在初始化…")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(
            "padding: 8px; background: #1f2937; border-radius: 4px;"
        )
        layout.addWidget(self.serial_label)
        layout.addWidget(self.serial_detail)
        layout.addWidget(self.message_label)

    def apply(self, view: MainWindowViewModel) -> None:
        self.serial_label.setText("串口状态：%s" % view.serial_text)
        self.serial_detail.setText(view.serial_detail)
        self.message_label.setText(view.message)

    def show_error(self, message: str) -> None:
        self.message_label.setText("错误：%s" % message)
        self.message_label.setStyleSheet(
            "padding: 8px; background: #7f1d1d; color: white; border-radius: 4px;"
        )
