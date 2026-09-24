"""Resolve the operator-selected person across short tracker-ID changes."""

from dataclasses import dataclass

from ..config.schema import TargetLockConfig
from ..domain.state import TargetStatus
from ..domain.tracking import TargetObservation, VisionSnapshot


@dataclass(frozen=True)
class TargetResolution:
    status: TargetStatus
    observation: TargetObservation | None = None
    released: bool = False


class TargetLock:
    def __init__(self, config: TargetLockConfig) -> None:
        self.config = config
        self._person_id = None
        self._last_observed_at = None

    @property
    def person_id(self):
        return self._person_id

    def lock(self, person_id: int) -> None:
        if self._person_id != int(person_id):
            self._person_id = int(person_id)
            self._last_observed_at = None

    def clear(self) -> None:
        self._person_id = None
        self._last_observed_at = None

    def resolve(
        self,
        snapshot: VisionSnapshot | None,
        timestamp_s: float,
    ) -> TargetResolution:
        if self._person_id is None:
            return TargetResolution(TargetStatus.NONE)

        # A fresh identity match cannot revive an already expired automatic lock.
        if (
            self._last_observed_at is not None
            and timestamp_s - self._last_observed_at > self.config.release_timeout_s
        ):
            return TargetResolution(TargetStatus.LOST, released=True)

        person = snapshot.find_person(self._person_id) if snapshot is not None else None
        usable = person is not None and person.confidence >= self.config.min_confidence
        if usable and person.observed:
            observed_at = snapshot.captured_at
            if self._last_observed_at is None or observed_at > self._last_observed_at:
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
