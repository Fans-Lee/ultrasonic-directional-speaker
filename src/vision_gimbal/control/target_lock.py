"""Resolve only the target explicitly activated by the operator."""

from dataclasses import dataclass
from typing import Optional

from ..config.schema import TargetLockConfig
from ..domain.state import TargetStatus
from ..domain.tracking import TargetObservation, VisionSnapshot


@dataclass(frozen=True)
class TargetResolution:
    status: TargetStatus
    observation: Optional[TargetObservation] = None
    released: bool = False


class TargetLock:
    def __init__(self, config: TargetLockConfig) -> None:
        self.config = config
        self._track_id = None
        self._last_observed_at = None

    @property
    def track_id(self):
        return self._track_id

    def lock(self, track_id: int) -> None:
        if self._track_id != int(track_id):
            self._track_id = int(track_id)
            self._last_observed_at = None

    def clear(self) -> None:
        self._track_id = None
        self._last_observed_at = None

    def resolve(
        self,
        snapshot: Optional[VisionSnapshot],
        timestamp_s: float,
    ) -> TargetResolution:
        if self._track_id is None:
            return TargetResolution(TargetStatus.NONE)

        person = snapshot.find(self._track_id) if snapshot is not None else None
        usable = (
            person is not None
            and person.confidence >= self.config.min_confidence
        )
        if usable and person.observed:
            observed_at = snapshot.captured_at
            if (
                self._last_observed_at is None
                or observed_at > self._last_observed_at
            ):
                self._last_observed_at = observed_at

        missing_for = float("inf")
        if self._last_observed_at is not None:
            missing_for = max(0.0, timestamp_s - self._last_observed_at)
        if (
            usable
            and person.observed
            and missing_for <= self.config.prediction_timeout_s
        ):
            return TargetResolution(
                TargetStatus.OBSERVED,
                self._to_observation(person, snapshot.captured_at),
            )
        if (
            usable
            and not person.observed
            and missing_for <= self.config.prediction_timeout_s
        ):
            return TargetResolution(
                TargetStatus.PREDICTED,
                self._to_observation(person, snapshot.captured_at),
            )
        if missing_for <= self.config.release_timeout_s:
            return TargetResolution(TargetStatus.LOST)
        return TargetResolution(TargetStatus.LOST, released=True)

    @staticmethod
    def _to_observation(person, timestamp_s: float) -> TargetObservation:
        return TargetObservation(
            timestamp_s=timestamp_s,
            track_id=person.track_id,
            aim_point=person.aim_point,
            confidence=person.confidence,
            observed=person.observed,
            bbox_xyxy=person.bbox_xyxy,
        )
