"""调用程序：组织摄像头、多人跟踪、逐 ID 平滑和结果显示。"""

import time
from dataclasses import dataclass

import cv2

if __package__:
    from .multi_person_tracker import UltralyticsMultiPersonTracker
    from .per_track_smoother import PerTrackAimSmoother
    from .tracking_renderer import render_tracks
else:
    from multi_person_tracker import UltralyticsMultiPersonTracker
    from per_track_smoother import PerTrackAimSmoother
    from tracking_renderer import render_tracks


@dataclass(frozen=True)
class TrackingConfig:
    camera_index: int = 0
    camera_rotation: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    camera_fps: int = 30
    model_path: str = "yolo26n.pt"
    tracker_config_path: str = "bytetrack.yaml"
    confidence: float = 0.10
    image_size: int = 512
    nms_iou_threshold: float = 0.60
    duplicate_iou_threshold: float = 0.70
    duplicate_containment_threshold: float = 0.90
    prediction_duplicate_iou_threshold: float = 0.55
    prediction_duplicate_containment_threshold: float = 0.85
    max_prediction_frames: int = 12
    device: str = "auto"
    window_name: str = "multi-person tracking"


def _open_camera(config):
    cap = cv2.VideoCapture(config.camera_index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.frame_height)
    cap.set(cv2.CAP_PROP_FPS, config.camera_fps)

    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"无法打开摄像头：index={config.camera_index}")
    return cap


def run_person_tracking(config):
    """持续跟踪画面中的全部人物，按 q 退出。"""
    cap = _open_camera(config)
    try:
        person_tracker = UltralyticsMultiPersonTracker(
            model_path=config.model_path,
            tracker_config_path=config.tracker_config_path,
            confidence=config.confidence,
            image_size=config.image_size,
            nms_iou_threshold=config.nms_iou_threshold,
            duplicate_iou_threshold=config.duplicate_iou_threshold,
            duplicate_containment_threshold=config.duplicate_containment_threshold,
            device=config.device,
            classes=(0,),
        )
        print(f"YOLO inference device: {person_tracker.device}")
        aim_smoother = PerTrackAimSmoother(
            config.max_prediction_frames,
            duplicate_iou_threshold=config.prediction_duplicate_iou_threshold,
            duplicate_containment_threshold=(
                config.prediction_duplicate_containment_threshold
            ),
        )
        last_time = time.monotonic()

        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            # 必须在 YOLO 和跟踪器处理之前校正方向。
            if config.camera_rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)

            observed_people = person_tracker.update(frame)

            now = time.monotonic()
            dt = now - last_time
            last_time = now
            tracked_people = aim_smoother.update(observed_people, dt)

            annotated = render_tracks(frame, tracked_people)
            cv2.imshow(config.window_name, annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
