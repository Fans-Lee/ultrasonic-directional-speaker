"""Live microphone and ultrasonic modulation controls."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..domain.audio import (
    AudioDriveMode,
    AudioModeSettings,
    AudioModulationMode,
    AudioProcessingMode,
)
from .view_models import MainWindowViewModel


class AudioPanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    settings_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._applying = False
        layout = QVBoxLayout(self)
        title = QLabel("麦克风与超声阵列")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.state_value = QLabel("-")
        self.detail_value = QLabel("")
        self.detail_value.setWordWrap(True)
        layout.addWidget(self.state_value)
        layout.addWidget(self.detail_value)

        grid = QGridLayout()
        self.processing_combo = QComboBox()
        self.processing_combo.addItem("RAW 原始", AudioProcessingMode.RAW.value)
        self.processing_combo.addItem("LOUD 响度增强", AudioProcessingMode.LOUD.value)
        self.modulation_combo = QComboBox()
        self.modulation_combo.addItem("DSB-AM", AudioModulationMode.DSB_AM.value)
        self.modulation_combo.addItem("SRAM", AudioModulationMode.SRAM.value)
        self.boost_check = QCheckBox("启用 BOOST")
        grid.addWidget(QLabel("处理"), 0, 0)
        grid.addWidget(self.processing_combo, 0, 1)
        grid.addWidget(QLabel("调制"), 1, 0)
        grid.addWidget(self.modulation_combo, 1, 1)
        grid.addWidget(self.boost_check, 2, 1)
        layout.addLayout(grid)

        button_grid = QGridLayout()
        self.start_button = QPushButton("开始麦克风链路")
        self.stop_button = QPushButton("关闭麦克风链路")
        self.start_button.setMinimumHeight(36)
        self.stop_button.setMinimumHeight(36)
        self.stop_button.setStyleSheet(
            "QPushButton { background: #b91c1c; color: white; font-weight: 600; }"
            "QPushButton:disabled { background: #6b7280; }"
        )
        button_grid.addWidget(self.start_button, 0, 0)
        button_grid.addWidget(self.stop_button, 0, 1)
        layout.addLayout(button_grid)

        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.processing_combo.currentIndexChanged.connect(self._emit_settings)
        self.modulation_combo.currentIndexChanged.connect(self._emit_settings)
        self.boost_check.toggled.connect(self._emit_settings)

    def _emit_settings(self, *_args) -> None:
        if self._applying:
            return
        self.settings_requested.emit(
            AudioModeSettings(
                processing=AudioProcessingMode(
                    self.processing_combo.currentData()
                ),
                drive=(
                    AudioDriveMode.BOOST
                    if self.boost_check.isChecked()
                    else AudioDriveMode.STANDARD
                ),
                modulation=AudioModulationMode(
                    self.modulation_combo.currentData()
                ),
            )
        )

    def apply(self, view: MainWindowViewModel) -> None:
        self.state_value.setText(f"链路状态：{view.audio_state_text}")
        self.detail_value.setText(view.audio_detail)
        self.start_button.setEnabled(view.audio_start_enabled)
        self.stop_button.setEnabled(view.audio_stop_enabled)
        self.processing_combo.setEnabled(view.audio_controls_enabled)
        self.modulation_combo.setEnabled(view.audio_controls_enabled)
        self.boost_check.setEnabled(view.audio_controls_enabled)

        settings = view.audio_settings
        self._applying = True
        try:
            processing_index = self.processing_combo.findData(
                settings.processing.value
            )
            modulation_index = self.modulation_combo.findData(
                settings.modulation.value
            )
            if processing_index >= 0:
                self.processing_combo.setCurrentIndex(processing_index)
            if modulation_index >= 0:
                self.modulation_combo.setCurrentIndex(modulation_index)
            self.boost_check.setChecked(settings.drive == AudioDriveMode.BOOST)
        finally:
            self._applying = False
