"""人物跟踪后处理的回归测试。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.config.schema import VisionConfig  # noqa: E402
from vision_gimbal.domain.tracking import TrackedPerson  # noqa: E402
from vision_gimbal.vision.duplicate_filter import (  # noqa: E402
    suppress_duplicate_people,
)
from vision_gimbal.vision.kalman_smoother import (  # noqa: E402
    PerTrackKalmanSmoother,
)
from vision_gimbal.vision.yolo_bytetrack import (  # noqa: E402
    YOLOByteTrackPeopleTracker,
)


def _person(track_id, bbox, confidence=0.8):
    x1, y1, x2, y2 = bbox
    center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    return TrackedPerson(track_id, bbox, center, center, confidence)


def _suppress(people):
    return suppress_duplicate_people(
        people,
        iou_threshold=0.70,
        containment_threshold=0.90,
    )


class DuplicateSuppressionTests(unittest.TestCase):
    def test_keeps_highest_confidence_duplicate(self):
        people = [
            _person(3, (10.0, 10.0, 110.0, 210.0), 0.72),
            _person(8, (13.0, 12.0, 108.0, 208.0), 0.91),
        ]

        result = _suppress(people)

        self.assertEqual([person.track_id for person in result], [8])

    def test_keeps_distinct_people(self):
        people = [
            _person(1, (10.0, 10.0, 110.0, 210.0)),
            _person(2, (90.0, 10.0, 190.0, 210.0)),
        ]

        result = _suppress(people)

        self.assertEqual([person.track_id for person in result], [1, 2])

    def test_keeps_much_smaller_person_inside_foreground_box(self):
        people = [
            _person(1, (0.0, 0.0, 300.0, 600.0), 0.9),
            _person(2, (100.0, 100.0, 180.0, 300.0), 0.8),
        ]

        result = _suppress(people)

        self.assertEqual([person.track_id for person in result], [1, 2])


class TrackerIntegrationTests(unittest.TestCase):
    def test_tracker_passes_nms_threshold_and_filters_duplicate_output(self):
        class FakeBoxes:
            xyxy = np.array(
                [
                    [10.0, 10.0, 110.0, 210.0],
                    [12.0, 12.0, 108.0, 208.0],
                ]
            )
            conf = np.array([0.75, 0.90])
            id = np.array([1, 9])

            def __len__(self):
                return 2

        class FakeModel:
            def __init__(self):
                self.arguments = None

            def track(self, **kwargs):
                self.arguments = kwargs
                return [SimpleNamespace(boxes=FakeBoxes())]

        fake_model = FakeModel()
        tracker = YOLOByteTrackPeopleTracker(
            VisionConfig(
                model_path="unused.pt",
                tracker_config_path="unused.yaml",
                nms_iou_threshold=0.6,
                device="cpu",
            ),
            model=fake_model,
        )

        result = tracker.update(np.zeros((8, 8, 3), dtype=np.uint8))

        self.assertEqual(fake_model.arguments["iou"], 0.6)
        self.assertEqual([person.track_id for person in result], [9])


class PredictionSuppressionTests(unittest.TestCase):
    def test_new_id_replaces_overlapping_old_prediction(self):
        smoother = PerTrackKalmanSmoother(VisionConfig(max_prediction_frames=30))
        smoother.update([_person(1, (10.0, 10.0, 110.0, 210.0))], 1 / 30)

        result = smoother.update(
            [_person(7, (12.0, 10.0, 112.0, 210.0))],
            1 / 30,
        )

        self.assertEqual([person.track_id for person in result], [7])
        self.assertTrue(result[0].observed)

    def test_non_overlapping_old_track_is_still_predicted(self):
        smoother = PerTrackKalmanSmoother(VisionConfig(max_prediction_frames=30))
        smoother.update([_person(1, (10.0, 10.0, 110.0, 210.0))], 1 / 30)

        result = smoother.update(
            [_person(2, (300.0, 10.0, 400.0, 210.0))],
            1 / 30,
        )

        self.assertEqual([person.track_id for person in result], [1, 2])
        self.assertFalse(result[0].observed)
        self.assertTrue(result[1].observed)


if __name__ == "__main__":
    unittest.main()
