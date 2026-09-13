"""Live microphone and ultrasonic modulation controls."""

from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..domain.audio import (
    AudioDriveMode,
    AudioModeSettings,
    AudioModulationMode,
    AudioProcessingMode,
    AudioSourceKind,
)
from .view_models import MainWindowViewModel


class AudioModeComboBox(QComboBox):
    """A combo box with a compact arrow that leaves wheel input to its parent."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Prevent wheel input from changing the selected option.

        Forward the event to the containing scroll area so the sidebar keeps
        scrolling even while the cursor is over an option.
        """
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                return
            parent = parent.parentWidget()
        event.ignore()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = "#67e8f9" if self.underMouse() and self.isEnabled() else "#9fb3cc"
        if not self.isEnabled():
            color = "#60738d"
        painter.setPen(QPen(QColor(color), 1.8))
        center_x = self.width() - 14.0
        center_y = self.height() / 2.0
        painter.drawLine(
            QPointF(center_x - 4.0, center_y - 2.0),
            QPointF(center_x, center_y + 2.0),
        )
        painter.drawLine(
            QPointF(center_x, center_y + 2.0),
            QPointF(center_x + 4.0, center_y - 2.0),
        )


class AudioPanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    source_requested = Signal(object)
    settings_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self._applying = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        eyebrow = QLabel("AUDIO ARRAY")
        eyebrow.setProperty("role", "eyebrow")
        title = QLabel("音频与超声阵列")
        title.setProperty("role", "section-title")
        subtitle = QLabel("配置音源、处理方式与阵列调制")
        subtitle.setProperty("role", "section-subtitle")
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        state_card = QFrame()
        state_card.setProperty("role", "inset")
        state_layout = QVBoxLayout(state_card)
        state_layout.setContentsMargins(12, 10, 12, 10)
        state_layout.setSpacing(4)
        self.state_value = QLabel("-")
        self.state_value.setProperty("role", "status")
        self.detail_value = QLabel("")
        self.detail_value.setWordWrap(True)
        self.detail_value.setProperty("role", "helper")
        state_layout.addWidget(self.state_value)
        state_layout.addWidget(self.detail_value)
        layout.addWidget(state_card)

        settings_card = QFrame()
        settings_card.setProperty("role", "inset")
        grid = QGridLayout()
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.source_combo = AudioModeComboBox()
        self.source_combo.addItem("麦克风", AudioSourceKind.MICROPHONE.value)
        self.source_combo.addItem(
            "电脑声音（立体声混音）", AudioSourceKind.STEREO_MIX.value
        )
        self.source_combo.addItem(
            "电脑声音（静音无关回环）",
            AudioSourceKind.SYSTEM_LOOPBACK.value,
        )
        self.processing_combo = AudioModeComboBox()
        self.processing_combo.addItem("RAW 原始", AudioProcessingMode.RAW.value)
        self.processing_combo.addItem("LOUD 响度增强", AudioProcessingMode.LOUD.value)
        self.modulation_combo = AudioModeComboBox()
        self.modulation_combo.addItem("DSB-AM", AudioModulationMode.DSB_AM.value)
        self.modulation_combo.addItem("SRAM", AudioModulationMode.SRAM.value)
        self.boost_check = QCheckBox("启用 BOOST")
        self.boost_check.setObjectName("boostToggle")
        self.boost_check.setProperty("boost", "off")
        for text, row in (("音源", 0), ("处理", 1), ("调制", 2)):
            label = QLabel(text)
            label.setProperty("role", "metric-label")
            grid.addWidget(label, row, 0)
        grid.addWidget(self.source_combo, 0, 1)
        grid.addWidget(self.processing_combo, 1, 1)
        grid.addWidget(self.modulation_combo, 2, 1)
        grid.addWidget(self.boost_check, 3, 1)
        settings_card.setLayout(grid)
        layout.addWidget(settings_card)

        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(8)
        self.start_button = QPushButton("开始音频链路")
        self.stop_button = QPushButton("关闭音频链路")
        self.start_button.setProperty("kind", "primary")
        self.stop_button.setProperty("kind", "danger")
        self.start_button.setMinimumHeight(40)
        self.stop_button.setMinimumHeight(40)
        button_grid.addWidget(self.start_button, 0, 0)
        button_grid.addWidget(self.stop_button, 0, 1)
        layout.addLayout(button_grid)

        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.source_combo.currentIndexChanged.connect(self._emit_source)
        self.processing_combo.currentIndexChanged.connect(self._emit_settings)
        self.modulation_combo.currentIndexChanged.connect(self._emit_settings)
        self.boost_check.toggled.connect(self._emit_settings)
        self.boost_check.toggled.connect(self._update_boost_presentation)
        self._update_boost_presentation(False)

    def _emit_source(self, *_args) -> None:
        if self._applying:
            return
        self.source_requested.emit(AudioSourceKind(self.source_combo.currentData()))

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

    def _update_boost_presentation(self, enabled: bool) -> None:
        """Keep BOOST state legible even when the indicator is not focused."""
        self.boost_check.setText(
            "✓ BOOST 已启用" if enabled else "○ BOOST 未启用"
        )
        self.boost_check.setProperty("boost", "on" if enabled else "off")
        style = self.boost_check.style()
        style.unpolish(self.boost_check)
        style.polish(self.boost_check)

    def apply(self, view: MainWindowViewModel) -> None:
        self.state_value.setText(f"链路状态：{view.audio_state_text}")
        self.detail_value.setText(view.audio_detail)
        self.start_button.setEnabled(view.audio_start_enabled)
        self.stop_button.setEnabled(view.audio_stop_enabled)
        self.source_combo.setEnabled(view.audio_controls_enabled)
        self.processing_combo.setEnabled(view.audio_controls_enabled)
        self.modulation_combo.setEnabled(view.audio_controls_enabled)
        self.boost_check.setEnabled(view.audio_controls_enabled)

        settings = view.audio_settings
        self._applying = True
        try:
            source_index = self.source_combo.findData(view.audio_source.value)
            processing_index = self.processing_combo.findData(
                settings.processing.value
            )
            modulation_index = self.modulation_combo.findData(
                settings.modulation.value
            )
            if source_index >= 0:
                self.source_combo.setCurrentIndex(source_index)
            if processing_index >= 0:
                self.processing_combo.setCurrentIndex(processing_index)
            if modulation_index >= 0:
                self.modulation_combo.setCurrentIndex(modulation_index)
            self.boost_check.setChecked(settings.drive == AudioDriveMode.BOOST)
        finally:
            self._applying = False
