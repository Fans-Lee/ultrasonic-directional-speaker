"""为每个人物 ID 维护独立的瞄准点 Kalman 滤波器。"""

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional

import cv2
import numpy as np

if __package__:
    from .tracking_geometry import boxes_are_duplicates, shift_bbox
    from .tracking_models import Point, TrackedPerson
else:
    from tracking_geometry import boxes_are_duplicates, shift_bbox
    from tracking_models import Point, TrackedPerson


class KalmanPointFilter:
    """使用二维匀速模型平滑一个人物的中心点。"""

    def __init__(self):
        self.filter = cv2.KalmanFilter(4, 2)
        self.filter.measurementMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32
        )
        self.filter.processNoiseCov = np.diag(
            [1.0, 1.0, 25.0, 25.0]
        ).astype(np.float32)
        self.filter.measurementNoiseCov = np.eye(2, dtype=np.float32) * 16.0
        self.filter.errorCovPost = np.eye(4, dtype=np.float32) * 10.0
        self.initialized = False

    def _set_dt(self, dt: float) -> None:
        self.filter.transitionMatrix = np.array(
            [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]],
            dtype=np.float32,
        )

    def predict(self, dt: float) -> Optional[Point]:
        if not self.initialized:
            return None

        self._set_dt(dt)
        prediction = self.filter.predict()
        return float(prediction[0, 0]), float(prediction[1, 0])

    def correct(self, point: Point) -> Point:
        x, y = point
        measurement = np.array([[x], [y]], dtype=np.float32)

        if not self.initialized:
            initial_state = np.array([[x], [y], [0], [0]], dtype=np.float32)
            self.filter.statePre = initial_state.copy()
            self.filter.statePost = initial_state.copy()
            self.initialized = True
            estimate = initial_state
        else:
            estimate = self.filter.correct(measurement)

        return float(estimate[0, 0]), float(estimate[1, 0])


@dataclass
class _TrackFilterState:
    point_filter: KalmanPointFilter
    last_person: TrackedPerson
    missed_frames: int = 0


class PerTrackAimSmoother:
    """按 track_id 平滑观测，并为短暂漏检的轨迹输出预测点。"""

    def __init__(
        self,
        max_prediction_frames: int = 12,
        duplicate_iou_threshold: float = 0.55,
        duplicate_containment_threshold: float = 0.85,
    ):
        if max_prediction_frames < 0:
            raise ValueError("max_prediction_frames 不能小于 0")
        for name, value in (
            ("duplicate_iou_threshold", duplicate_iou_threshold),
            ("duplicate_containment_threshold", duplicate_containment_threshold),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} 必须在 (0, 1] 范围内")
        self.max_prediction_frames = max_prediction_frames
        self.duplicate_iou_threshold = duplicate_iou_threshold
        self.duplicate_containment_threshold = duplicate_containment_threshold
        self._states: Dict[int, _TrackFilterState] = {}

    def update(
        self,
        observed_people: Iterable[TrackedPerson],
        dt: float,
    ) -> List[TrackedPerson]:
        dt = min(max(float(dt), 1.0 / 120.0), 0.25)
        predictions = {
            track_id: state.point_filter.predict(dt)
            for track_id, state in self._states.items()
        }

        output = []
        observed_ids = set()
        for person in observed_people:
            if person.track_id in observed_ids:
                raise ValueError(f"当前帧出现重复 track_id：{person.track_id}")
            observed_ids.add(person.track_id)

            state = self._states.get(person.track_id)
            if state is None:
                point_filter = KalmanPointFilter()
                aim_point = point_filter.correct(person.detection_center)
                state = _TrackFilterState(point_filter, person)
                self._states[person.track_id] = state
            else:
                aim_point = state.point_filter.correct(person.detection_center)

            smoothed_person = replace(
                person,
                aim_point=aim_point,
                observed=True,
            )
            state.last_person = smoothed_person
            state.missed_frames = 0
            output.append(smoothed_person)

        for track_id in list(self._states):
            if track_id in observed_ids:
                continue

            state = self._states[track_id]
            state.missed_frames += 1
            prediction = predictions[track_id]
            if (
                state.missed_frames > self.max_prediction_frames
                or prediction is None
            ):
                del self._states[track_id]
                continue

            predicted_bbox = shift_bbox(
                state.last_person.bbox_xyxy,
                state.last_person.detection_center,
                prediction,
            )
            if any(
                boxes_are_duplicates(
                    predicted_bbox,
                    person.bbox_xyxy,
                    self.duplicate_iou_threshold,
                    self.duplicate_containment_threshold,
                )
                for person in output
                if person.observed
            ):
                # 常见于跟踪器切换 ID：新观测应覆盖旧 ID 的外推框。
                del self._states[track_id]
                continue

            predicted_person = replace(
                state.last_person,
                aim_point=prediction,
                observed=False,
            )
            state.last_person = predicted_person
            output.append(predicted_person)

        return sorted(output, key=lambda person: person.track_id)

    def reset(self) -> None:
        self._states.clear()
