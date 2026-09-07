"""Qt thread adapters around synchronous application services."""

import threading

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ..application.latest_snapshot import LatestSnapshotStore
from ..application.runtime import ApplicationRuntime
from ..application.vision_service import DisplayFrame
from ..domain.intents import StopTracking


class VisionWorker(QObject):
    failed = Signal(str)
    finished = Signal()

    def __init__(self, service, display_frames) -> None:
        super().__init__()
        self.service = service
        self.display_frames = display_frames
        self._stop_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.display_frames.set(self.service.step())
        except Exception as error:
            if not self._stop_event.is_set():
                self.failed.emit(str(error))
        finally:
            self.finished.emit()

    def request_stop(self) -> None:
        self._stop_event.set()


class ControlWorker(QObject):
    state_ready = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, service, interval_ms: int) -> None:
        super().__init__()
        self.service = service
        self.interval_ms = interval_ms
        self._stop_event = threading.Event()
        self._timer = None

    @Slot()
    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(self.interval_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    @Slot()
    def _tick(self) -> None:
        if self._stop_event.is_set():
            self._timer.stop()
            self.finished.emit()
            return
        try:
            self.state_ready.emit(self.service.tick())
        except Exception as error:
            self._timer.stop()
            self.failed.emit(str(error))
            self.finished.emit()

    def request_stop(self) -> None:
        self._stop_event.set()


class QtApplicationRuntime(QObject):
    frame_ready = Signal(object)
    state_ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        application: ApplicationRuntime,
        control_hz: float,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.application = application
        self.control_hz = control_hz
        self._display_frames = LatestSnapshotStore[DisplayFrame]()
        self._last_displayed_frame_id = -1
        self._vision_thread = None
        self._control_thread = None
        self._vision_worker = None
        self._control_worker = None
        self._display_timer = QTimer(self)
        self._display_timer.setInterval(33)
        self._display_timer.timeout.connect(self._publish_latest_frame)
        self._started = False

    def submit(self, intent) -> None:
        self.application.control.submit(intent)

    def start(self) -> None:
        if self._started:
            return
        self.application.start()
        self._started = True

        self._vision_thread = QThread(self)
        self._vision_worker = VisionWorker(
            self.application.vision,
            self._display_frames,
        )
        self._vision_worker.moveToThread(self._vision_thread)
        self._vision_thread.started.connect(self._vision_worker.run)
        self._vision_worker.finished.connect(self._vision_thread.quit)
        self._vision_worker.failed.connect(self._worker_failed)

        self._control_thread = QThread(self)
        interval_ms = max(1, round(1000.0 / self.control_hz))
        self._control_worker = ControlWorker(
            self.application.control,
            interval_ms,
        )
        self._control_worker.moveToThread(self._control_thread)
        self._control_thread.started.connect(self._control_worker.start)
        self._control_worker.finished.connect(self._control_thread.quit)
        self._control_worker.state_ready.connect(self.state_ready.emit)
        self._control_worker.failed.connect(self._worker_failed)

        self._vision_thread.start()
        self._control_thread.start()
        self._display_timer.start()

    @Slot(str)
    def _worker_failed(self, message: str) -> None:
        self.application.control.submit(StopTracking())
        self.failed.emit(message)

    @Slot()
    def _publish_latest_frame(self) -> None:
        display = self._display_frames.get()
        if (
            display is not None
            and display.snapshot.frame_id != self._last_displayed_frame_id
        ):
            self._last_displayed_frame_id = display.snapshot.frame_id
            self.frame_ready.emit(display)

    def stop(self) -> None:
        if not self._started:
            return
        self._display_timer.stop()
        if self._vision_worker is not None:
            self._vision_worker.request_stop()
        if self._control_worker is not None:
            self._control_worker.request_stop()
        if self._control_thread is not None:
            if not self._control_thread.wait(1000):
                self._control_thread.quit()
                self._control_thread.wait(1000)
        if self._vision_thread is not None:
            if not self._vision_thread.wait(10000):
                self.failed.emit("视觉线程未能在 10 秒内停止")
                self._vision_thread.wait()
        self.application.close()
        self._display_frames.clear()
        self._started = False
