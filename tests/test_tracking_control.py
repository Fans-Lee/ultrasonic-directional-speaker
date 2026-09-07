"""Unit tests for target selection and visual gimbal control."""

import math
import sys
import unittest
from pathlib import Path


CV_TEST_DIR = Path(__file__).resolve().parents[1] / "src" / "cv_test"
sys.path.insert(0, str(CV_TEST_DIR))

from camera_geometry import CameraGeometry, CameraGeometryConfig  # noqa: E402
from close_range_aim import (  # noqa: E402
    CloseRangeAimConfig,
    CloseRangeAimPolicy,
)
from control_models import (  # noqa: E402
    AimObservation,
    GimbalSetpoint,
    SerialLinkStatus,
)
from gimbal_serial import encode_gimbal_command  # noqa: E402
from target_selector import TargetSelector, TargetSelectorConfig  # noqa: E402
from tracking_controller import (  # noqa: E402
    TrackingController,
    TrackingControllerConfig,
)
from tracking_models import TrackedPerson  # noqa: E402
from visual_servo import (  # noqa: E402
    AxisPidConfig,
    VisualServoConfig,
    VisualServoController,
)


def _person(track_id, center, confidence=0.8, observed=True):
    x, y = center
    return TrackedPerson(
        track_id=track_id,
        bbox_xyxy=(x - 10.0, y - 20.0, x + 10.0, y + 20.0),
        detection_center=center,
        aim_point=center,
        confidence=confidence,
        observed=observed,
    )


class _RecordingGimbal:
    def __init__(self):
        self.commands = []
        self.started = False

    def start(self):
        self.started = True

    def publish(self, setpoint):
        self.commands.append(setpoint)

    def status(self):
        return SerialLinkStatus(enabled=False, connected=False)

    def close(self):
        self.started = False


class TargetSelectorTests(unittest.TestCase):
    def test_locks_nearest_observed_person(self):
        selector = TargetSelector(TargetSelectorConfig())

        first = selector.update(
            [_person(1, (15.0, 15.0)), _person(2, (52.0, 51.0))],
            timestamp_s=1.0,
            aim_center=(50.0, 50.0),
        )
        second = selector.update(
            [_person(1, (50.0, 50.0)), _person(2, (70.0, 50.0))],
            timestamp_s=1.1,
            aim_center=(50.0, 50.0),
        )

        self.assertEqual(first.track_id, 2)
        self.assertEqual(second.track_id, 2)

    def test_releases_target_after_timeout(self):
        selector = TargetSelector(
            TargetSelectorConfig(
                prediction_timeout_s=0.2,
                release_timeout_s=0.5,
            )
        )
        selector.update(
            [_person(3, (50.0, 50.0))],
            timestamp_s=2.0,
            aim_center=(50.0, 50.0),
        )

        self.assertIsNone(
            selector.update([], 2.3, aim_center=(50.0, 50.0))
        )
        self.assertEqual(selector.selected_track_id, 3)
        self.assertIsNone(
            selector.update([], 2.6, aim_center=(50.0, 50.0))
        )
        self.assertIsNone(selector.selected_track_id)


class CameraGeometryTests(unittest.TestCase):
    def test_converts_edge_displacement_to_angle(self):
        geometry = CameraGeometry(
            CameraGeometryConfig(
                horizontal_fov_deg=90.0,
                vertical_fov_deg=90.0,
            )
        )
        observation = AimObservation(
            timestamp_s=1.0,
            track_id=1,
            aim_point=(100.0, 100.0),
            confidence=0.9,
            observed=True,
        )

        pan, tilt = geometry.error_angles_deg(observation, (100, 100))

        self.assertTrue(math.isclose(pan, -45.0, abs_tol=1e-6))
        self.assertTrue(math.isclose(tilt, -45.0, abs_tol=1e-6))


class CloseRangeAimPolicyTests(unittest.TestCase):
    def test_uses_upper_body_after_confirmed_oversized_box(self):
        policy = CloseRangeAimPolicy(
            CloseRangeAimConfig(
                enter_height_ratio=0.90,
                exit_height_ratio=0.70,
                upper_body_fraction=0.30,
                enter_confirmed_frames=2,
                exit_confirmed_frames=2,
                ratio_ema_alpha=1.0,
            )
        )
        full_height = AimObservation(
            timestamp_s=1.0,
            track_id=6,
            aim_point=(50.0, 50.0),
            confidence=0.9,
            observed=True,
            bbox_xyxy=(20.0, 0.0, 80.0, 100.0),
        )

        first, first_status = policy.update(full_height, (100, 100))
        second, second_status = policy.update(full_height, (100, 100))

        self.assertFalse(first_status.active)
        self.assertEqual(first.aim_point, (50.0, 50.0))
        self.assertTrue(second_status.active)
        self.assertEqual(second.aim_point, (50.0, 30.0))

    def test_exits_only_when_smaller_box_is_fully_visible(self):
        policy = CloseRangeAimPolicy(
            CloseRangeAimConfig(
                enter_confirmed_frames=1,
                exit_confirmed_frames=2,
                ratio_ema_alpha=1.0,
            )
        )
        full_height = AimObservation(
            timestamp_s=1.0,
            track_id=6,
            aim_point=(50.0, 50.0),
            confidence=0.9,
            observed=True,
            bbox_xyxy=(20.0, 0.0, 80.0, 100.0),
        )
        smaller_visible = AimObservation(
            timestamp_s=1.1,
            track_id=6,
            aim_point=(50.0, 50.0),
            confidence=0.9,
            observed=True,
            bbox_xyxy=(20.0, 20.0, 80.0, 80.0),
        )
        policy.update(full_height, (100, 100))

        first, first_status = policy.update(smaller_visible, (100, 100))
        second, second_status = policy.update(smaller_visible, (100, 100))

        self.assertTrue(first_status.active)
        self.assertNotEqual(first.aim_point, (50.0, 50.0))
        self.assertFalse(second_status.active)
        self.assertEqual(second.aim_point, (50.0, 50.0))

    def test_prediction_cannot_enter_close_range_mode(self):
        policy = CloseRangeAimPolicy(
            CloseRangeAimConfig(enter_confirmed_frames=1)
        )
        predicted = AimObservation(
            timestamp_s=1.0,
            track_id=6,
            aim_point=(50.0, 50.0),
            confidence=0.9,
            observed=False,
            bbox_xyxy=(20.0, 0.0, 80.0, 100.0),
        )

        result, status = policy.update(predicted, (100, 100))

        self.assertFalse(status.active)
        self.assertEqual(result.aim_point, (50.0, 50.0))


class VisualServoTests(unittest.TestCase):
    def test_moves_towards_target_and_respects_angle_limit(self):
        axis = AxisPidConfig(
            kp=2.0,
            ki=0.0,
            kd=0.0,
            deadband_deg=0.0,
            max_speed_deg_s=100.0,
            max_accel_deg_s2=1000.0,
            min_angle_deg=-2.0,
            max_angle_deg=2.0,
        )
        servo = VisualServoController(
            VisualServoConfig(pan=axis, tilt=axis),
            CameraGeometry(
                CameraGeometryConfig(
                    horizontal_fov_deg=90.0,
                    vertical_fov_deg=90.0,
                )
            ),
        )
        observation = AimObservation(
            timestamp_s=1.0,
            track_id=4,
            aim_point=(100.0, 50.0),
            confidence=0.9,
            observed=True,
        )

        output = servo.update(observation, (100, 100), 1.0)
        for index in range(1, 5):
            output = servo.update(
                observation,
                (100, 100),
                1.0 + index * 0.1,
            )

        self.assertIsNotNone(output.setpoint)
        self.assertEqual(output.setpoint.pan_degrees, -2.0)
        self.assertEqual(output.setpoint.tilt_degrees, 0.0)


class TrackingControllerTests(unittest.TestCase):
    def test_limits_command_publication_rate(self):
        gimbal = _RecordingGimbal()
        controller = TrackingController(
            TrackingControllerConfig(update_hz=10.0),
            gimbal,
        )
        people = [_person(8, (80.0, 50.0))]

        controller.start()
        controller.update(people, (100, 100), 10.0)
        controller.update(people, (100, 100), 10.05)
        controller.update(people, (100, 100), 10.11)
        controller.close()

        self.assertEqual(len(gimbal.commands), 2)


class GimbalProtocolTests(unittest.TestCase):
    def test_encodes_existing_firmware_syntax(self):
        command = encode_gimbal_command(
            GimbalSetpoint(1.0, pan_degrees=-12.4, tilt_degrees=8.2)
        )

        self.assertEqual(command, b"(-12,8)")


if __name__ == "__main__":
    unittest.main()
