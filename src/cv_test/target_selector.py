"""Stable target selection for multi-person tracking output."""

from dataclasses import dataclass
from typing import Optional, Sequence

if __package__:
    from .control_models import AimObservation, Point
    from .tracking_models import TrackedPerson
else:
    from control_models import AimObservation, Point
    from tracking_models import TrackedPerson


@dataclass(frozen=True)
class TargetSelectorConfig:
    min_confidence: float = 0.10
    prediction_timeout_s: float = 0.20
    release_timeout_s: float = 0.80

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        if self.prediction_timeout_s < 0.0:
            raise ValueError("prediction_timeout_s cannot be negative")
        if self.release_timeout_s < self.prediction_timeout_s:
            raise ValueError(
                "release_timeout_s must be >= prediction_timeout_s"
            )


class TargetSelector:
    """Lock one track ID and avoid switching targets on every frame."""

    def __init__(self, config: TargetSelectorConfig) -> None:
        self.config = config
        self._selected_track_id: Optional[int] = None
        self._last_observed_at: Optional[float] = None

    @property
    def selected_track_id(self) -> Optional[int]:
        return self._selected_track_id

    def lock(self, track_id: int) -> None:
        self._selected_track_id = int(track_id)
        self._last_observed_at = None

    def clear(self) -> None:
        self._selected_track_id = None
        self._last_observed_at = None

    def update(
        self,
        people: Sequence[TrackedPerson],
        timestamp_s: float,
        aim_center: Point,
    ) -> Optional[AimObservation]:
        if self._selected_track_id is not None:
            selected = next(
                (
                    person
                    for person in people
                    if person.track_id == self._selected_track_id
                ),
                None,
            )
            observation = self._use_selected(selected, timestamp_s)
            if observation is not None:
                return observation

            if self._last_observed_at is not None:
                missing_for = timestamp_s - self._last_observed_at
                if missing_for <= self.config.release_timeout_s:
                    return None
            self.clear()

        candidates = [
            person
            for person in people
            if person.observed
            and person.confidence >= self.config.min_confidence
        ]
        if not candidates:
            return None

        center_x, center_y = aim_center
        selected = min(
            candidates,
            key=lambda person: (
                (person.aim_point[0] - center_x) ** 2
                + (person.aim_point[1] - center_y) ** 2,
                -person.confidence,
                person.track_id,
            ),
        )
        self._selected_track_id = selected.track_id
        self._last_observed_at = timestamp_s
        return self._to_observation(selected, timestamp_s)

    def _use_selected(
        self,
        person: Optional[TrackedPerson],
        timestamp_s: float,
    ) -> Optional[AimObservation]:
        if person is None or person.confidence < self.config.min_confidence:
            return None

        if person.observed:
            self._last_observed_at = timestamp_s
            return self._to_observation(person, timestamp_s)

        if self._last_observed_at is None:
            return None
        if (
            timestamp_s - self._last_observed_at
            > self.config.prediction_timeout_s
        ):
            return None
        return self._to_observation(person, timestamp_s)

    @staticmethod
    def _to_observation(
        person: TrackedPerson,
        timestamp_s: float,
    ) -> AimObservation:
        return AimObservation(
            timestamp_s=timestamp_s,
            track_id=person.track_id,
            aim_point=person.aim_point,
            confidence=person.confidence,
            observed=person.observed,
            bbox_xyxy=person.bbox_xyxy,
        )

