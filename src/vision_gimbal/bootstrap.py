"""Composition root: wire every concrete adapter in one place."""

from dataclasses import dataclass

from .application.control_service import ControlService
from .application.latest_snapshot import LatestSnapshotStore
from .application.runtime import ApplicationRuntime
from .application.tracking_session import TrackingSession
from .application.vision_service import VisionService
from .config.schema import AppConfig
from .control.auto_tracking import AutoTrackingController
from .control.camera_projection import CameraProjection
from .control.close_range_aim import CloseRangeAimPolicy
from .control.command_arbiter import CommandArbiter
from .control.manual_jog import ManualJogController
from .control.motion_limiter import GimbalMotionLimiter
from .control.target_lock import TargetLock
from .infrastructure.opencv_camera import OpenCVCamera
from .infrastructure.serial_gimbal import create_gimbal_sink
from .infrastructure.system_clock import SystemClock
from .ui.main_window import MainWindow
from .ui.qt_workers import QtApplicationRuntime
from .vision.kalman_smoother import PerTrackKalmanSmoother
from .vision.pipeline import VisionPipeline
from .vision.yolo_bytetrack import YOLOByteTrackPeopleTracker


@dataclass(frozen=True)
class ApplicationBundle:
    window: MainWindow
    runtime: QtApplicationRuntime
    inference_device: str


def build_application(config: AppConfig) -> ApplicationBundle:
    clock = SystemClock()
    snapshots = LatestSnapshotStore()
    camera = OpenCVCamera(config.camera)
    tracker = YOLOByteTrackPeopleTracker(config.vision)
    smoother = PerTrackKalmanSmoother(config.vision)
    pipeline = VisionPipeline(tracker, smoother)
    vision_service = VisionService(camera, pipeline, clock, snapshots)

    automatic = AutoTrackingController(
        config.automatic,
        CameraProjection(config.projection),
        CloseRangeAimPolicy(config.close_range),
        config.motion,
    )
    control_service = ControlService(
        TrackingSession(config.target),
        TargetLock(config.target),
        automatic,
        ManualJogController(config.manual),
        CommandArbiter(),
        GimbalMotionLimiter(config.motion),
        create_gimbal_sink(config.serial),
        clock,
        snapshots,
    )
    application = ApplicationRuntime(vision_service, control_service)
    runtime = QtApplicationRuntime(application, config.runtime.control_hz)
    window = MainWindow(config.ui)
    window.intent_emitted.connect(runtime.submit)
    runtime.frame_ready.connect(window.apply_display_frame)
    runtime.state_ready.connect(window.apply_ui_snapshot)
    runtime.failed.connect(window.show_runtime_error)
    return ApplicationBundle(window, runtime, tracker.device)
