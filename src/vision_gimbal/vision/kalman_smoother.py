"""Maintain one constant-velocity Kalman filter per track ID."""

from collections.abc import Iterable
from dataclasses import dataclass, replace

import cv2
import numpy as np

from ..config.schema import VisionConfig
from ..domain.geometry import Point
from ..domain.tracking import TrackedPerson
from .duplicate_filter import boxes_are_duplicates, shift_bbox


class KalmanPointFilter:
    def __init__(self) -> None:
        self.filter = cv2.KalmanFilter(4, 2)
        self.filter.measurementMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32
        )
        self.filter.processNoiseCov = np.diag([1.0, 1.0, 25.0, 25.0]).astype(np.float32)
        self.filter.measurementNoiseCov = np.eye(2, dtype=np.float32) * 16.0
        self.filter.errorCovPost = np.eye(4, dtype=np.float32) * 10.0
        self.initialized = False

    def _set_dt(self, dt_s: float) -> None:
        self.filter.transitionMatrix = np.array(
            [
                [1, 0, dt_s, 0],
                [0, 1, 0, dt_s],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            dtype=np.float32,
        )

    def predict(self, dt_s: float) -> Point | None:
        if not self.initialized:
            return None
        self._set_dt(dt_s)
        prediction = self.filter.predict()
        return float(prediction[0, 0]), float(prediction[1, 0])

    def correct(self, point: Point) -> Point:
        x, y = point
        measurement = np.array([[x], [y]], dtype=np.float32)
        if not self.initialized:
            estimate = np.array([[x], [y], [0], [0]], dtype=np.float32)
            self.filter.statePre = estimate.copy()
            self.filter.statePost = estimate.copy()
            self.initialized = True
        else:
            estimate = self.filter.correct(measurement)
        return float(estimate[0, 0]), float(estimate[1, 0])


@dataclass
class _TrackState:
    point_filter: KalmanPointFilter
    last_person: TrackedPerson
    missed_frames: int = 0


class PerTrackKalmanSmoother:
    def __init__(self, config: VisionConfig) -> None:
        self.config = config
        self._states: dict[int, _TrackState] = {}

    def update(
        self,
        observed_people: Iterable[TrackedPerson],
        dt_s: float,
    ) -> list[TrackedPerson]:
        dt_s = min(max(float(dt_s), 1.0 / 120.0), 0.25)
        predictions = {
            track_id: state.point_filter.predict(dt_s)
            for track_id, state in self._states.items()
        }

        output = []
        observed_ids = set()
        for person in observed_people:
            if person.track_id in observed_ids:
                raise ValueError(f"duplicate track_id in frame: {person.track_id}")
            observed_ids.add(person.track_id)
            state = self._states.get(person.track_id)
            if state is None:
                point_filter = KalmanPointFilter()
                aim_point = point_filter.correct(person.detection_center)
                state = _TrackState(point_filter, person)
                self._states[person.track_id] = state
            else:
                aim_point = state.point_filter.correct(person.detection_center)

            smoothed = replace(person, aim_point=aim_point, observed=True)
            state.last_person = smoothed
            state.missed_frames = 0
            output.append(smoothed)

        for track_id in list(self._states):
            if track_id in observed_ids:
                continue
            state = self._states[track_id]
            state.missed_frames += 1
            prediction = predictions[track_id]
            if (
                state.missed_frames > self.config.max_prediction_frames
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
                    self.config.prediction_duplicate_iou_threshold,
                    self.config.prediction_duplicate_containment_threshold,
                )
                for person in output
                if person.observed
            ):
                del self._states[track_id]
                continue

            predicted = replace(
                state.last_person,
                bbox_xyxy=predicted_bbox,
                detection_center=prediction,
                aim_point=prediction,
                observed=False,
            )
            state.last_person = predicted
            output.append(predicted)

        return sorted(output, key=lambda item: item.track_id)

    def reset(self) -> None:
        self._states.clear()
