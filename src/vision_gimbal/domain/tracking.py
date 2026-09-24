"""Stable data contracts produced by the vision pipeline."""

from dataclasses import dataclass

from .geometry import BoundingBox, FrameSize, Point


@dataclass(frozen=True)
class TrackedPerson:
    track_id: int
    bbox_xyxy: BoundingBox
    detection_center: Point
    aim_point: Point
    confidence: float
    observed: bool = True
    person_id: int | None = None


@dataclass(frozen=True)
class TargetObservation:
    timestamp_s: float
    track_id: int
    aim_point: Point
    confidence: float
    observed: bool
    bbox_xyxy: BoundingBox


@dataclass(frozen=True)
class VisionSnapshot:
    frame_id: int
    captured_at: float
    frame_size: FrameSize
    tracks: tuple[TrackedPerson, ...] = ()

    def find(self, track_id: int):
        return next(
            (track for track in self.tracks if track.track_id == track_id),
            None,
        )

    def find_person(self, person_id: int):
        observed = next(
            (track for track in self.tracks if track.person_id == person_id and track.observed),
            None,
        )
        return observed or next(
            (track for track in self.tracks if track.person_id == person_id), None
        )
