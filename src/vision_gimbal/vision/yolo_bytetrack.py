"""Ultralytics YOLO and ByteTrack adapter."""

from collections.abc import Sequence
from typing import Any

import numpy as np
import torch
from ultralytics import YOLO

from ..config.schema import VisionConfig
from ..domain.tracking import TrackedPerson
from .duplicate_filter import suppress_duplicate_people


def _to_numpy(value):
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def resolve_inference_device(requested_device: str = "auto") -> str:
    device = str(requested_device).strip().lower()
    if device not in ("", "auto"):
        return device
    if torch.cuda.is_available():
        return "cuda:0"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu:0"
    return "cpu"


class YOLOByteTrackPeopleTracker:
    def __init__(
        self,
        config: VisionConfig,
        classes: Sequence[int] = (0,),
        model: Any = None,
    ) -> None:
        self.config = config
        self.model = model if model is not None else YOLO(config.model_path)
        self.classes = tuple(classes)
        self.device = resolve_inference_device(config.device)

    def update(self, frame: Any):
        results = self.model.track(
            source=frame,
            persist=True,
            tracker=self.config.tracker_config_path,
            classes=list(self.classes),
            conf=self.config.confidence,
            iou=self.config.nms_iou_threshold,
            imgsz=self.config.image_size,
            device=self.device,
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
            self.config.duplicate_iou_threshold,
            self.config.duplicate_containment_threshold,
        )

    def reset(self) -> None:
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", ()) or ():
            reset = getattr(tracker, "reset", None)
            if reset is not None:
                reset()
