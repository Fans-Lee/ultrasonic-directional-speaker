"""CPU appearance sampling and persistent person identity behavior."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vision_gimbal.config.schema import (  # noqa: E402
    AppearanceConfig,
    TargetLockConfig,
    VisionConfig,
)
from vision_gimbal.control.target_lock import TargetLock  # noqa: E402
from vision_gimbal.domain.state import TargetStatus  # noqa: E402
from vision_gimbal.domain.tracking import TrackedPerson, VisionSnapshot  # noqa: E402
from vision_gimbal.vision.appearance import (  # noqa: E402
    HsvAppearanceEncoder,
    IdentityGallery,
)
from vision_gimbal.vision.kalman_smoother import PerTrackKalmanSmoother  # noqa: E402
from vision_gimbal.vision.pipeline import VisionPipeline  # noqa: E402


def _track(track_id, key, observed=True, confidence=0.9):
    return TrackedPerson(
        track_id,
        (float(key), 0.0, float(key + 50), 100.0),
        (float(key + 25), 50.0),
        (float(key + 25), 50.0),
        confidence,
        observed,
    )


class _Encoder:
    def __init__(self):
        self.calls = []

    def encode(self, frame, bbox_xyxy):
        del frame
        key = int(bbox_xyxy[0])
        self.calls.append(key)
        return np.array([1.0, 0.0] if key == 0 else [0.0, 1.0], dtype=np.float32)


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 120, 3), dtype=np.uint8)
        self.encoder = _Encoder()
        self.gallery = IdentityGallery(
            AppearanceConfig(sample_interval_s=1.0, gallery_ttl_s=5.0),
            self.encoder,
        )

    def test_samples_new_tracks_then_only_at_interval_and_reuses_person_id(self):
        first = self.gallery.update(self.frame, [_track(10, 0)], 0.0)
        self.assertIsNone(first[0].person_id)
        confirmed = self.gallery.update(self.frame, [_track(10, 0)], 0.1)
        self.assertEqual(confirmed[0].person_id, 1)
        self.gallery.update(self.frame, [_track(10, 0)], 0.5)
        self.assertEqual(self.encoder.calls, [0, 0])
        self.gallery.update(self.frame, [_track(10, 0)], 1.2)
        self.assertEqual(self.encoder.calls, [0, 0, 0])
        self.gallery.update(self.frame, [], 1.3)
        pending = self.gallery.update(self.frame, [_track(27, 0)], 2.0)
        self.assertIsNone(pending[0].person_id)
        returned = self.gallery.update(self.frame, [_track(27, 0)], 2.1)
        self.assertEqual(returned[0].person_id, 1)
        self.assertEqual(self.encoder.calls, [0, 0, 0, 0, 0])

    def test_does_not_give_two_visible_people_the_same_identity(self):
        self.gallery.update(self.frame, [_track(10, 0)], 0.0)
        first = self.gallery.update(self.frame, [_track(10, 0)], 0.1)
        simultaneous = self.gallery.update(
            self.frame, [_track(10, 0), _track(11, 0)], 0.2
        )
        confirmed = self.gallery.update(
            self.frame, [_track(10, 0), _track(11, 0)], 0.3
        )
        self.assertEqual(first[0].person_id, 1)
        self.assertEqual({person.person_id for person in simultaneous}, {1, None})
        self.assertEqual({person.person_id for person in confirmed}, {1, 2})

    def test_predictions_and_low_quality_boxes_do_not_extract(self):
        waiting = self.gallery.update(
            self.frame, [_track(10, 0, confidence=0.2)], 0.0
        )
        self.assertIsNone(waiting[0].person_id)
        self.assertEqual(self.encoder.calls, [])
        self.gallery.update(self.frame, [_track(10, 0)], 0.1)
        observed = self.gallery.update(self.frame, [_track(10, 0)], 0.2)
        predicted = self.gallery.update(
            self.frame, [_track(10, 0, observed=False)], 0.3
        )
        self.assertEqual(observed[0].person_id, 1)
        self.assertEqual(predicted[0].person_id, 1)
        self.assertEqual(self.encoder.calls, [0, 0])

    def test_disabled_appearance_keeps_tracker_ids_without_cpu_extraction(self):
        gallery = IdentityGallery(AppearanceConfig(enabled=False), self.encoder)
        people = gallery.update(self.frame, [_track(27, 0)], 0.0)
        self.assertEqual(people[0].person_id, 27)
        self.assertEqual(self.encoder.calls, [])

    def test_expired_gallery_does_not_match(self):
        self.gallery.update(self.frame, [_track(10, 0)], 0.0)
        self.gallery.update(self.frame, [_track(10, 0)], 0.1)
        self.gallery.update(self.frame, [], 0.1)
        self.gallery.update(self.frame, [_track(20, 0)], 6.0)
        returned = self.gallery.update(self.frame, [_track(20, 0)], 6.1)
        self.assertEqual(returned[0].person_id, 2)

    def test_ambiguous_new_track_has_bounded_initial_sampling(self):
        class ChangingEncoder(_Encoder):
            def __init__(self):
                super().__init__()
                self.new_calls = 0

            def encode(self, frame, bbox_xyxy):
                key = int(bbox_xyxy[0])
                if key != 2:
                    return super().encode(frame, bbox_xyxy)
                self.calls.append(key)
                self.new_calls += 1
                return np.array(
                    [1.0, 0.0] if self.new_calls % 2 else [0.0, 1.0],
                    dtype=np.float32,
                )

        encoder = ChangingEncoder()
        gallery = IdentityGallery(AppearanceConfig(), encoder)
        for timestamp in (0.0, 0.1):
            gallery.update(self.frame, [_track(10, 0)], timestamp)
        for timestamp in (0.2, 0.3):
            gallery.update(self.frame, [_track(10, 0), _track(11, 1)], timestamp)
        gallery.update(self.frame, [], 0.4)
        ids = [
            gallery.update(self.frame, [_track(27, 2)], timestamp)[0].person_id
            for timestamp in (0.5, 0.6, 0.7, 0.8)
        ]
        self.assertEqual(ids, [None, None, None, 3])
        gallery.update(self.frame, [_track(27, 2)], 0.9)
        self.assertEqual(encoder.new_calls, 4)

    def test_hsv_descriptor_uses_upper_and_lower_clothing(self):
        encoder = HsvAppearanceEncoder()
        first = np.zeros((100, 50, 3), dtype=np.uint8)
        first[:50] = (0, 0, 255)
        first[50:] = (255, 0, 0)
        swapped = first[::-1].copy()
        a = encoder.encode(first, (0, 0, 50, 100))
        b = encoder.encode(swapped, (0, 0, 50, 100))
        self.assertAlmostEqual(float(np.dot(a, a)), 1.0, places=5)
        self.assertLess(float(np.dot(a, b)), 0.88)

    def test_target_lock_follows_reidentified_person_to_new_track(self):
        lock = TargetLock(TargetLockConfig(release_timeout_s=0.8))
        lock.lock(7)
        first = _track(10, 0)
        second = _track(27, 0)
        first = replace(first, person_id=7)
        second = replace(second, person_id=7)
        self.assertEqual(
            lock.resolve(VisionSnapshot(1, 1.0, (120, 120), (first,)), 1.0).status,
            TargetStatus.OBSERVED,
        )
        result = lock.resolve(
            VisionSnapshot(2, 1.3, (120, 120), (second,)), 1.3
        )
        self.assertEqual(result.status, TargetStatus.OBSERVED)
        self.assertEqual(result.observation.track_id, 27)

    def test_pipeline_reidentifies_after_tracker_changes_id(self):
        class Tracker:
            def __init__(self):
                self.frames = iter(
                    ([_track(10, 0)], [_track(10, 0)], [],
                     [_track(27, 0)], [_track(27, 0)])
                )

            def update(self, frame):
                del frame
                return next(self.frames)

            def reset(self):
                pass

        pipeline = VisionPipeline(
            Tracker(),
            PerTrackKalmanSmoother(VisionConfig()),
            IdentityGallery(AppearanceConfig(), _Encoder()),
        )
        snapshots = [
            pipeline.process(self.frame, frame_id, timestamp)
            for frame_id, timestamp in enumerate((0.0, 0.1, 0.2, 0.3, 0.4), 1)
        ]
        self.assertEqual(snapshots[1].find_person(1).track_id, 10)
        self.assertIsNone(snapshots[3].find(27).person_id)
        self.assertEqual(snapshots[4].find_person(1).track_id, 27)

    def test_expired_lock_does_not_revive_after_a_late_match(self):
        lock = TargetLock(TargetLockConfig(release_timeout_s=0.8))
        lock.lock(7)
        first = replace(_track(10, 0), person_id=7)
        returned = replace(_track(27, 0), person_id=7)
        lock.resolve(VisionSnapshot(1, 1.0, (120, 120), (first,)), 1.0)
        result = lock.resolve(
            VisionSnapshot(2, 2.0, (120, 120), (returned,)), 2.0
        )
        self.assertTrue(result.released)


if __name__ == "__main__":
    unittest.main()
