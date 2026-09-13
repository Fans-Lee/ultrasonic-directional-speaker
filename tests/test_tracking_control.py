"""Unit tests for the current visual-gimbal control primitives."""

import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.config.schema import (  # noqa: E402
    AutoControlConfig,
    AxisMotionConfig,
    AxisPidConfig,
    CameraProjectionConfig,
    CloseRangeConfig,
    GimbalMotionConfig,
    TargetLockConfig,
)
from vision_gimbal.control.auto_tracking import AutoTrackingController  # noqa: E402
from vision_gimbal.control.camera_projection import CameraProjection  # noqa: E402
from vision_gimbal.control.close_range_aim import CloseRangeAimPolicy  # noqa: E402
from vision_gimbal.control.motion_limiter import GimbalMotionLimiter  # noqa: E402
from vision_gimbal.control.target_lock import TargetLock  # noqa: E402
from vision_gimbal.domain.state import TargetStatus  # noqa: E402
from vision_gimbal.domain.tracking import (  # noqa: E402
    TargetObservation,
    TrackedPerson,
    VisionSnapshot,
)


def _observation(
    track_id=1,
    aim_point=(50.0, 50.0),
    bbox=(20.0, 20.0, 80.0, 80.0),
    timestamp_s=1.0,
    observed=True,
):
    return TargetObservation(
        timestamp_s=timestamp_s,
        track_id=track_id,
        aim_point=aim_point,
        confidence=0.9,
        observed=observed,
        bbox_xyxy=bbox,
    )


class TargetLockTests(unittest.TestCase):
    def test_releases_only_the_explicit_target_after_timeout(self):
        target_lock = TargetLock(
            TargetLockConfig(prediction_timeout_s=0.2, release_timeout_s=0.5)
        )
        target_lock.lock(3)
        person = TrackedPerson(
            3,
            (40.0, 30.0, 60.0, 70.0),
            (50.0, 50.0),
            (50.0, 50.0),
            0.9,
        )
        observed = VisionSnapshot(1, 2.0, (100, 100), (person,))
        missing = VisionSnapshot(2, 2.3, (100, 100), ())

        self.assertEqual(
            target_lock.resolve(observed, 2.0).status,
            TargetStatus.OBSERVED,
        )
        interim = target_lock.resolve(missing, 2.3)
        expired = target_lock.resolve(missing, 2.6)

        self.assertEqual(interim.status, TargetStatus.LOST)
        self.assertFalse(interim.released)
        self.assertTrue(expired.released)
        self.assertEqual(target_lock.track_id, 3)


class CameraProjectionTests(unittest.TestCase):
    def test_converts_edge_displacement_to_angle(self):
        projection = CameraProjection(
            CameraProjectionConfig(
                horizontal_fov_deg=90.0,
                vertical_fov_deg=90.0,
            )
        )

        error = projection.error(
            _observation(aim_point=(100.0, 100.0)),
            (100, 100),
        )

        self.assertTrue(math.isclose(error.pan_degrees, -45.0, abs_tol=1e-6))
        self.assertTrue(math.isclose(error.tilt_degrees, -45.0, abs_tol=1e-6))


class CloseRangeAimPolicyTests(unittest.TestCase):
    def test_uses_upper_body_after_confirmed_oversized_box(self):
        policy = CloseRangeAimPolicy(
            CloseRangeConfig(
                enter_height_ratio=0.90,
                exit_height_ratio=0.70,
                upper_body_fraction=0.30,
                enter_confirmed_frames=2,
                exit_confirmed_frames=2,
                ratio_ema_alpha=1.0,
            )
        )
        first_observation = _observation(
            track_id=6,
            bbox=(20.0, 0.0, 80.0, 100.0),
            timestamp_s=1.0,
        )
        second_observation = _observation(
            track_id=6,
            bbox=(20.0, 0.0, 80.0, 100.0),
            timestamp_s=1.1,
        )

        first, first_status = policy.update(first_observation, (100, 100))
        second, second_status = policy.update(second_observation, (100, 100))

        self.assertFalse(first_status.active)
        self.assertEqual(first.aim_point, (50.0, 50.0))
        self.assertTrue(second_status.active)
        self.assertEqual(second.aim_point, (50.0, 30.0))

    def test_exits_only_when_smaller_box_is_fully_visible(self):
        policy = CloseRangeAimPolicy(
            CloseRangeConfig(
                enter_confirmed_frames=1,
                exit_confirmed_frames=2,
                ratio_ema_alpha=1.0,
            )
        )
        policy.update(
            _observation(track_id=6, bbox=(20.0, 0.0, 80.0, 100.0)),
            (100, 100),
        )

        first, first_status = policy.update(
            _observation(
                track_id=6,
                bbox=(20.0, 20.0, 80.0, 80.0),
                timestamp_s=1.1,
            ),
            (100, 100),
        )
        second, second_status = policy.update(
            _observation(
                track_id=6,
                bbox=(20.0, 20.0, 80.0, 80.0),
                timestamp_s=1.2,
            ),
            (100, 100),
        )

        self.assertTrue(first_status.active)
        self.assertNotEqual(first.aim_point, (50.0, 50.0))
        self.assertFalse(second_status.active)
        self.assertEqual(second.aim_point, (50.0, 50.0))

    def test_prediction_cannot_enter_close_range_mode(self):
        policy = CloseRangeAimPolicy(CloseRangeConfig(enter_confirmed_frames=1))

        result, status = policy.update(
            _observation(
                track_id=6,
                bbox=(20.0, 0.0, 80.0, 100.0),
                observed=False,
            ),
            (100, 100),
        )

        self.assertFalse(status.active)
        self.assertEqual(result.aim_point, (50.0, 50.0))


class AutoTrackingTests(unittest.TestCase):
    def test_request_moves_towards_target_and_motion_limiter_clamps_pose(self):
        pid = AxisPidConfig(
            kp=2.0,
            ki=0.0,
            kd=0.0,
            deadband_deg=0.0,
            integral_limit=10.0,
            output_limit_deg_s=100.0,
        )
        axis_motion = AxisMotionConfig(
            min_angle_deg=-2.0,
            max_angle_deg=2.0,
            max_speed_deg_s=100.0,
            max_accel_deg_s2=1000.0,
        )
        motion = GimbalMotionConfig(
            pan=axis_motion,
            tilt=axis_motion,
            nominal_dt_s=0.1,
            maximum_dt_s=0.5,
        )
        automatic = AutoTrackingController(
            AutoControlConfig(
                pan_pid=pid,
                tilt_pid=pid,
                nominal_dt_s=0.1,
                maximum_dt_s=0.5,
            ),
            CameraProjection(
                CameraProjectionConfig(
                    horizontal_fov_deg=90.0,
                    vertical_fov_deg=90.0,
                )
            ),
            CloseRangeAimPolicy(CloseRangeConfig()),
            motion,
        )
        limiter = GimbalMotionLimiter(motion)

        request, telemetry = automatic.update(
            _observation(track_id=4, aim_point=(100.0, 50.0)),
            (100, 100),
            1.0,
            limiter.pose,
        )
        setpoint = limiter.update(request, 1.0)

        self.assertLess(request.pan_velocity_deg_s, 0.0)
        self.assertEqual(setpoint.pan_degrees, -2.0)
        self.assertEqual(setpoint.tilt_degrees, 0.0)
        self.assertTrue(telemetry.target_observed)


if __name__ == "__main__":
    unittest.main()
