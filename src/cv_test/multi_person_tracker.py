"""Ultralytics 多人物跟踪适配器。"""

from typing import Any, List, Protocol, Sequence

import numpy as np
from ultralytics import YOLO

if __package__:
    from .tracking_geometry import boxes_are_duplicates
    from .tracking_models import TrackedPerson
else:
    from tracking_geometry import boxes_are_duplicates
    from tracking_models import TrackedPerson


class MultiPersonTracker(Protocol):
    """调用层依赖的多人物跟踪接口。"""

    def update(self, frame: np.ndarray) -> List[TrackedPerson]:
        """处理一帧并返回当前已确认的人物轨迹。"""


def _to_numpy(value):
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def suppress_duplicate_people(
    people: Sequence[TrackedPerson],
    iou_threshold: float = 0.70,
    containment_threshold: float = 0.90,
) -> List[TrackedPerson]:
    """置信度优先地移除几乎重合或互相包含的人物框。"""
    kept = []
    for person in sorted(people, key=lambda item: item.confidence, reverse=True):
        if any(
            boxes_are_duplicates(
                person.bbox_xyxy,
                other.bbox_xyxy,
                iou_threshold,
                containment_threshold,
            )
            for other in kept
        ):
            continue
        kept.append(person)
    return sorted(kept, key=lambda person: person.track_id)


class UltralyticsMultiPersonTracker:
    """使用 YOLO + ByteTrack/BoT-SORT 产生跨帧稳定的 track_id。"""

    def __init__(
        self,
        model_path: str,
        tracker_config_path: str,
        confidence: float = 0.1,
        image_size: int = 512,
        nms_iou_threshold: float = 0.60,
        duplicate_iou_threshold: float = 0.70,
        duplicate_containment_threshold: float = 0.90,
        classes: Sequence[int] = (0,),
        model: Any = None,
    ):
        for name, value in (
            ("nms_iou_threshold", nms_iou_threshold),
            ("duplicate_iou_threshold", duplicate_iou_threshold),
            ("duplicate_containment_threshold", duplicate_containment_threshold),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} 必须在 (0, 1] 范围内")

        self.model = model if model is not None else YOLO(model_path)
        self.tracker_config_path = tracker_config_path
        self.confidence = confidence
        self.image_size = image_size
        self.nms_iou_threshold = nms_iou_threshold
        self.duplicate_iou_threshold = duplicate_iou_threshold
        self.duplicate_containment_threshold = duplicate_containment_threshold
        self.classes = tuple(classes)

    def update(self, frame: np.ndarray) -> List[TrackedPerson]:
        results = self.model.track(
            source=frame,
            persist=True,
            tracker=self.tracker_config_path,
            classes=list(self.classes),
            conf=self.confidence,
            iou=self.nms_iou_threshold,
            imgsz=self.image_size,
            verbose=False,
        )
        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0 or boxes.id is None:
            return []

        xyxy = _to_numpy(boxes.xyxy)
        confidences = _to_numpy(boxes.conf)
        track_ids = _to_numpy(boxes.id).astype(np.int64)

        people = []
        for bbox, confidence, track_id in zip(xyxy, confidences, track_ids):
            x1, y1, x2, y2 = (float(value) for value in bbox)
            center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            people.append(
                TrackedPerson(
                    track_id=int(track_id),
                    bbox_xyxy=(x1, y1, x2, y2),
                    detection_center=center,
                    aim_point=center,
                    confidence=float(confidence),
                )
            )
        return suppress_duplicate_people(
            people,
            iou_threshold=self.duplicate_iou_threshold,
            containment_threshold=self.duplicate_containment_threshold,
        )
