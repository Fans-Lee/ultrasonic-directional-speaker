"""Top-level window; emits intents and renders snapshots only."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from ..application.vision_service import DisplayFrame
from ..config.schema import UiConfig
from ..domain.intents import (
    ClearManualKeys,
    ManualKeyChanged,
    SelectTarget,
    ShutdownRequested,
    StartTracking,
    StopTracking,
)
from ..domain.state import UiSnapshot
from .control_panel import ControlPanel
from .key_input import ManualKeyFilter
from .presenter import present
from .status_panel import StatusPanel
from .video_canvas import VideoCanvas


class MainWindow(QMainWindow):
    intent_emitted = Signal(object)

    def __init__(self, config: UiConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(config.window_title)
        self.resize(config.initial_width, config.initial_height)

        central = QWidget()
        root = QHBoxLayout(central)
        self.video = VideoCanvas()
        root.addWidget(self.video, 1)

        sidebar = QWidget()
        sidebar.setFixedWidth(310)
        sidebar_layout = QVBoxLayout(sidebar)
        self.controls = ControlPanel()
        self.status = StatusPanel()
        sidebar_layout.addWidget(self.controls, 1)
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
        self.status.apply(view)

    def show_runtime_error(self, message: str) -> None:
        self.status.show_error(message)

    def _select_target(self, track_id: int, frame_id: int) -> None:
        self.intent_emitted.emit(SelectTarget(track_id, frame_id))

    def _manual_key(self, direction, pressed: bool) -> None:
        self.intent_emitted.emit(ManualKeyChanged(direction, pressed))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.intent_emitted.emit(ShutdownRequested())
        event.accept()
