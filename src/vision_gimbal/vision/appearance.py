"""CPU appearance descriptors and a short-lived, session-local person gallery."""

from collections import deque
from dataclasses import dataclass, field, replace
from typing import Protocol

import cv2
import numpy as np

from ..config.schema import AppearanceConfig
from ..domain.tracking import TrackedPerson


class AppearanceEncoder(Protocol):
    def encode(self, frame: np.ndarray, bbox_xyxy) -> np.ndarray | None: ...


class HsvAppearanceEncoder:
    """Compact clothing-color descriptor; replaceable by a trained ReID encoder."""

    def encode(self, frame: np.ndarray, bbox_xyxy) -> np.ndarray | None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = bbox_xyxy
        left, top = max(0, int(x1)), max(0, int(y1))
        right, bottom = min(width, int(x2)), min(height, int(y2))
        if right <= left or bottom <= top:
            return None
        crop = frame[top:bottom, left:right]
        # Suppress much of the background at either side of a loose person box.
        margin = round(crop.shape[1] * 0.15)
        if crop.shape[1] > 2 * margin + 1:
            crop = crop[:, margin : crop.shape[1] - margin]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h = hsv.shape[0]
        regions = (
            hsv[int(0.12 * h) : int(0.48 * h)],
            hsv[int(0.48 * h) : int(0.88 * h)],
        )
        parts = []
        for region in regions:
            if region.size == 0:
                return None
            color = cv2.calcHist([region], [0, 1], None, [12, 4], [0, 180, 0, 256])
            value = cv2.calcHist([region], [2], None, [8], [0, 256])
            color = color.ravel() / max(float(color.sum()), 1.0)
            value = value.ravel() / max(float(value.sum()), 1.0)
            parts.extend((color, 0.4 * value))
        descriptor = np.concatenate(parts).astype(np.float32)
        norm = float(np.linalg.norm(descriptor))
        return descriptor / norm if norm > 0 else None


@dataclass
class _Identity:
    samples: deque[np.ndarray] = field(default_factory=deque)
    last_seen_at: float = 0.0


class IdentityGallery:
    """Bind short tracker IDs to person IDs without extracting on every frame."""

    def __init__(
        self,
        config: AppearanceConfig,
        encoder: AppearanceEncoder | None = None,
    ) -> None:
        self.config = config
        self.encoder = encoder or HsvAppearanceEncoder()
        self._track_to_person: dict[int, int] = {}
        self._pending_matches: dict[int, tuple[int, int]] = {}
        self._unmatched_counts: dict[int, int] = {}
        self._initial_sample_counts: dict[int, int] = {}
        self._last_sample_at: dict[int, float] = {}
        self._identities: dict[int, _Identity] = {}
        self._next_person_id = 1

    def update(
        self,
        frame: np.ndarray,
        tracks: tuple[TrackedPerson, ...] | list[TrackedPerson],
        timestamp_s: float,
    ) -> tuple[TrackedPerson, ...]:
        if not self.config.enabled:
            return tuple(replace(track, person_id=track.track_id) for track in tracks)

        present_track_ids = {track.track_id for track in tracks}
        self._track_to_person = {
            track_id: person_id
            for track_id, person_id in self._track_to_person.items()
            if track_id in present_track_ids
        }
        self._last_sample_at = {
            track_id: sampled_at
            for track_id, sampled_at in self._last_sample_at.items()
            if track_id in present_track_ids
        }
        self._pending_matches = {
            track_id: pending
            for track_id, pending in self._pending_matches.items()
            if track_id in present_track_ids
        }
        self._unmatched_counts = {
            track_id: count
            for track_id, count in self._unmatched_counts.items()
            if track_id in present_track_ids
        }
        self._initial_sample_counts = {
            track_id: count
            for track_id, count in self._initial_sample_counts.items()
            if track_id in present_track_ids
        }
        self._identities = {
            person_id: identity
            for person_id, identity in self._identities.items()
            if timestamp_s - identity.last_seen_at <= self.config.gallery_ttl_s
            or person_id in self._track_to_person.values()
        }

        observed = sorted(
            (track for track in tracks if track.observed),
            key=lambda track: -track.confidence,
        )
        reserved = {
            self._track_to_person[track.track_id]
            for track in observed
            if self._track_to_person.get(track.track_id) in self._identities
        }
        occupied: set[int] = set()
        output: dict[int, TrackedPerson] = {}
        for track in observed:
            person_id = self._track_to_person.get(track.track_id)
            if person_id in occupied or person_id not in self._identities:
                self._track_to_person.pop(track.track_id, None)
                person_id = None

            should_sample = person_id is None or (
                timestamp_s - self._last_sample_at.get(track.track_id, float("-inf"))
                >= self.config.sample_interval_s
            )
            feature = self._feature(frame, track) if should_sample else None
            if should_sample and feature is not None:
                self._last_sample_at[track.track_id] = timestamp_s

            if person_id is None and feature is not None:
                self._initial_sample_counts[track.track_id] = (
                    self._initial_sample_counts.get(track.track_id, 0) + 1
                )
                match_id = self._match(feature, occupied | reserved, timestamp_s)
                if match_id is not None and self.config.match_confirmations > 1:
                    self._unmatched_counts.pop(track.track_id, None)
                    previous = self._pending_matches.get(track.track_id)
                    count = previous[1] + 1 if previous and previous[0] == match_id else 1
                    if count < self.config.match_confirmations:
                        self._pending_matches[track.track_id] = (match_id, count)
                    else:
                        person_id = match_id
                        self._pending_matches.pop(track.track_id, None)
                else:
                    person_id = match_id
                    self._pending_matches.pop(track.track_id, None)
                if person_id is None and match_id is None:
                    count = self._unmatched_counts.get(track.track_id, 0) + 1
                    self._unmatched_counts[track.track_id] = count
                if person_id is None and (
                    self._unmatched_counts.get(track.track_id, 0)
                    >= self.config.match_confirmations
                    or self._initial_sample_counts[track.track_id]
                    >= self.config.max_initial_samples
                ):
                    person_id = self._next_person_id
                    self._next_person_id += 1
                    self._identities[person_id] = _Identity()
                if person_id is not None:
                    self._unmatched_counts.pop(track.track_id, None)
                    self._initial_sample_counts.pop(track.track_id, None)
                    self._track_to_person[track.track_id] = person_id

            if person_id is not None:
                occupied.add(person_id)
                identity = self._identities[person_id]
                identity.last_seen_at = timestamp_s
                if feature is not None and self._safe_to_update(identity, feature):
                    identity.samples.append(feature)
                    while len(identity.samples) > self.config.max_samples_per_person:
                        identity.samples.popleft()
            output[track.track_id] = replace(track, person_id=person_id)

        for track in tracks:
            if track.observed:
                continue
            person_id = self._track_to_person.get(track.track_id)
            # The old Kalman prediction must not duplicate a reattached person.
            if person_id in occupied:
                continue
            output[track.track_id] = replace(track, person_id=person_id)
        return tuple(output[track.track_id] for track in tracks if track.track_id in output)

    def _feature(self, frame: np.ndarray, track: TrackedPerson) -> np.ndarray | None:
        x1, y1, x2, y2 = track.bbox_xyxy
        if (
            track.confidence < self.config.min_confidence
            or x2 - x1 < self.config.min_box_width_px
            or y2 - y1 < self.config.min_box_height_px
        ):
            return None
        feature = self.encoder.encode(frame, track.bbox_xyxy)
        if feature is None:
            return None
        feature = np.asarray(feature, dtype=np.float32).reshape(-1)
        if not feature.size or not np.isfinite(feature).all():
            return None
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm > 0 else None

    def _match(
        self, feature: np.ndarray, occupied: set[int], timestamp_s: float
    ) -> int | None:
        scores = sorted(
            (
                (
                    max(float(np.dot(feature, sample)) for sample in identity.samples),
                    person_id,
                )
                for person_id, identity in self._identities.items()
                if identity.samples
                and person_id not in occupied
                and timestamp_s - identity.last_seen_at <= self.config.gallery_ttl_s
            ),
            reverse=True,
        )
        if not scores or scores[0][0] < self.config.match_similarity:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < self.config.match_margin:
            return None
        return scores[0][1]

    def _safe_to_update(self, identity: _Identity, feature: np.ndarray) -> bool:
        return not identity.samples or max(
            float(np.dot(feature, sample)) for sample in identity.samples
        ) >= self.config.update_similarity

    def reset(self) -> None:
        self._track_to_person.clear()
        self._pending_matches.clear()
        self._unmatched_counts.clear()
        self._initial_sample_counts.clear()
        self._last_sample_at.clear()
        self._identities.clear()
        self._next_person_id = 1
