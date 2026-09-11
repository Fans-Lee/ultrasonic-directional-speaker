"""Top-level window; emits intents and renders snapshots only."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..application.vision_service import DisplayFrame
from ..audio.spectrum import AudioSpectrumSnapshot
from ..config.schema import UiConfig
from ..domain.intents import (
    ClearManualKeys,
    ConfigureAudio,
    ManualKeyChanged,
    SelectTarget,
    ShutdownRequested,
    StartAudio,
    StartTracking,
    StopAudio,
    StopTracking,
)
from ..domain.state import UiSnapshot
from .audio_panel import AudioPanel
from .control_panel import ControlPanel
from .key_input import ManualKeyFilter
from .presenter import present
from .spectrum_panel import SpectrumPanel
from .status_panel import StatusPanel
from .video_canvas import VideoCanvas


class MainWindow(QMainWindow):
    intent_emitted = Signal(object)

    def __init__(
        self,
        config: UiConfig,
        spectrum_enabled: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(config.window_title)
        self.resize(config.initial_width, config.initial_height)

        central = QWidget()
        root = QHBoxLayout(central)
        visual_splitter = QSplitter(Qt.Orientation.Vertical)
        self.video = VideoCanvas()
        self.spectrum = SpectrumPanel()
        visual_splitter.addWidget(self.video)
        visual_splitter.addWidget(self.spectrum)
        self.spectrum.setVisible(spectrum_enabled)
        visual_splitter.setStretchFactor(0, 3)
        visual_splitter.setStretchFactor(1, 1)
        visual_splitter.setSizes([520, 220])
        root.addWidget(visual_splitter, 1)

        sidebar = QWidget()
        sidebar.setFixedWidth(350)
        sidebar_layout = QVBoxLayout(sidebar)
        self.controls = ControlPanel()
        self.audio = AudioPanel()
        self.status = StatusPanel()
        sidebar_layout.addWidget(self.controls)
        sidebar_layout.addWidget(self.audio)
        sidebar_layout.addStretch(1)
        sidebar_layout.addWidget(self.status)
        root.addWidget(sidebar)
        self.setCentralWidget(central)

        self.key_filter = ManualKeyFilter(self)
        QApplication.instance().installEventFilter(self.key_filter)
        self.video.target_selected.connect(self._select_target)
        self.controls.start_requested.connect(
            lambda: self.intent_emitted.emit(StartTracking())
        )
        self.controls.stop_requested.connect(
            lambda: self.intent_emitted.emit(StopTracking())
        )
        self.audio.start_requested.connect(
            lambda: self.intent_emitted.emit(StartAudio())
        )
        self.audio.stop_requested.connect(
            lambda: self.intent_emitted.emit(StopAudio())
        )
        self.audio.settings_requested.connect(
            lambda settings: self.intent_emitted.emit(ConfigureAudio(settings))
        )
        self.key_filter.direction_changed.connect(self._manual_key)
        self.key_filter.clear_requested.connect(
            lambda: self.intent_emitted.emit(ClearManualKeys())
        )

    def apply_display_frame(self, frame: DisplayFrame) -> None:
        self.video.set_display_frame(frame)

    def apply_ui_snapshot(self, snapshot: UiSnapshot) -> None:
        view = present(snapshot)
        self.video.set_state(snapshot)
        self.controls.apply(view)
        self.audio.apply(view)
        self.status.apply(view)

    def apply_spectrum_snapshot(self, snapshot: AudioSpectrumSnapshot) -> None:
        self.spectrum.apply(snapshot)

    def show_runtime_error(self, message: str) -> None:
        self.status.show_error(message)

    def _select_target(self, track_id: int, frame_id: int) -> None:
        self.intent_emitted.emit(SelectTarget(track_id, frame_id))

    def _manual_key(self, direction, pressed: bool) -> None:
        self.intent_emitted.emit(ManualKeyChanged(direction, pressed))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.intent_emitted.emit(ShutdownRequested())
        event.accept()
