"""Top-level window; emits intents and renders snapshots only."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..application.vision_service import DisplayFrame
from ..audio.spectrum import AudioSpectrumSnapshot
from ..domain.spatial_field import SpatialFieldSnapshot
from ..config.schema import UiConfig
from ..domain.intents import (
    ClearManualKeys,
    ConfigureAudio,
    ManualKeyChanged,
    SelectAudioSource,
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
from .sound_field_panel import SoundFieldPanel
from .spectrum_panel import SpectrumPanel
from .status_panel import StatusPanel
from .theme import APP_STYLESHEET
from .video_canvas import VideoCanvas


class MainWindow(QMainWindow):
    intent_emitted = Signal(object)

    def __init__(
        self,
        config: UiConfig,
        spectrum_enabled: bool = True,
        spatial_enabled: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(config.window_title)
        self.resize(config.initial_width, config.initial_height)
        self.setMinimumSize(1080, 680)
        self.setStyleSheet(APP_STYLESHEET)

        central = QWidget()
        central.setObjectName("appRoot")
        root = QHBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        visual_workspace = QFrame()
        visual_workspace.setObjectName("visualWorkspace")
        workspace_layout = QVBoxLayout(visual_workspace)
        workspace_layout.setContentsMargins(18, 14, 18, 18)
        workspace_layout.setSpacing(8)

        visual_header = QWidget()
        visual_header_layout = QVBoxLayout(visual_header)
        visual_header_layout.setContentsMargins(2, 0, 2, 0)
        visual_header_layout.setSpacing(2)
        eyebrow = QLabel("LIVE CONTROL")
        eyebrow.setProperty("role", "eyebrow")
        visual_header_layout.addWidget(eyebrow)
        title = QLabel("视觉与声束监控")
        title.setProperty("role", "app-title")
        visual_header_layout.addWidget(title)
        workspace_layout.addWidget(visual_header)

        self.visual_tabs = QTabWidget()
        self.visual_tabs.setDocumentMode(True)
        self.video = VideoCanvas()
        self.sound_field = SoundFieldPanel()
        self.spectrum = SpectrumPanel()
        self.visual_tabs.addTab(self.video, "追踪画面")
        if spatial_enabled:
            self.visual_tabs.addTab(self.sound_field, "声场模拟")
        if spectrum_enabled:
            self.visual_tabs.addTab(self.spectrum, "实时频谱")
        workspace_layout.addWidget(self.visual_tabs, 1)
        root.addWidget(visual_workspace, 1)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(360)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        sidebar_content = QWidget()
        sidebar_content.setObjectName("sidebarContent")
        sidebar_content.setMinimumWidth(342)
        sidebar_content_layout = QVBoxLayout(sidebar_content)
        sidebar_content_layout.setContentsMargins(0, 0, 4, 0)
        sidebar_content_layout.setSpacing(12)

        self.controls = ControlPanel()
        self.audio = AudioPanel()
        self.status = StatusPanel()
        sidebar_content_layout.addWidget(self.controls)
        sidebar_content_layout.addWidget(self.audio)
        sidebar_content_layout.addWidget(self.status)
        sidebar_content_layout.addStretch(1)
        sidebar_scroll.setWidget(sidebar_content)
        sidebar_layout.addWidget(sidebar_scroll)
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
        self.audio.source_requested.connect(
            lambda source: self.intent_emitted.emit(SelectAudioSource(source))
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

    def apply_spatial_field_snapshot(self, snapshot: SpatialFieldSnapshot) -> None:
        self.sound_field.set_spatial_field_snapshot(snapshot)

    def show_runtime_error(self, message: str) -> None:
        self.status.show_error(message)

    def _select_target(self, track_id: int, frame_id: int) -> None:
        self.intent_emitted.emit(SelectTarget(track_id, frame_id))

    def _manual_key(self, direction, pressed: bool) -> None:
        self.intent_emitted.emit(ManualKeyChanged(direction, pressed))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.intent_emitted.emit(ShutdownRequested())
        event.accept()
