"""Unit tests for the optional low-priority spatial-analysis path."""

import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.application.spatial_field_service import SpatialFieldService
from vision_gimbal.config.schema import (
    AppConfig,
    CameraCalibrationConfig,
    SpatialDepthTemporalConfig,
    SpatialFieldConfig,
)
from vision_gimbal.domain.tracking import VisionSnapshot
from vision_gimbal.spatial.field import CameraIntrinsics, RelativeFreeFieldModel
from vision_gimbal.spatial.temporal import TemporalDepthStabilizer
from vision_gimbal.domain.spatial_field import SpatialFieldSnapshot
from vision_gimbal.ui.overlay_renderer import render_sound_field_overlay


class _Estimator:
    def __init__(self, value=2.0) -> None:
        self.value = value
        self.calls = 0

    def estimate(self, image):
        self.calls += 1
        height, width = image.shape[:2]
        return np.full((height, width), self.value, dtype=np.float32)


class CameraIntrinsicsTests(unittest.TestCase):
    def test_calibration_scales_to_active_camera_resolution(self):
        intrinsics = CameraIntrinsics.from_calibration(
            CameraCalibrationConfig(),
            (1280, 720),
        )
        self.assertAlmostEqual(intrinsics.fx, 1450.0 * 2.0 / 3.0)
        self.assertAlmostEqual(intrinsics.fy, 1450.0 * 2.0 / 3.0)
        self.assertEqual((intrinsics.cx, intrinsics.cy), (640.0, 360.0))


class RelativeFreeFieldTests(unittest.TestCase):
    def test_center_ray_is_louder_than_off_axis_ray(self):
        config = AppConfig()
        model = RelativeFreeFieldModel(
            config.camera.calibration,
            config.spatial_field.acoustics,
            0.4,
            10.0,
        )
        depth = np.full((3, 3), 2.0, dtype=np.float32)
        levels = model.evaluate(depth, (1280, 720))
        self.assertAlmostEqual(float(levels[1, 1]), -6.0206, places=2)
        self.assertLess(float(levels[0, 0]), float(levels[1, 1]))

    def test_invalid_depth_is_not_assigned_a_sound_level(self):
        config = AppConfig()
        model = RelativeFreeFieldModel(
            config.camera.calibration,
            config.spatial_field.acoustics,
            0.4,
            10.0,
        )
        levels = model.evaluate(
            np.array([[0.2, np.nan], [2.0, 12.0]], dtype=np.float32),
            (1280, 720),
        )
        self.assertTrue(np.isnan(levels[0, 0]))
        self.assertTrue(np.isnan(levels[0, 1]))
        self.assertTrue(np.isfinite(levels[1, 0]))
        self.assertTrue(np.isnan(levels[1, 1]))

    def test_nonzero_distortion_uses_opencv_undistortion_path(self):
        app_config = AppConfig()
        calibration = replace(
            app_config.camera.calibration,
            distortion=(0.02, -0.01, 0.0, 0.0, 0.0),
        )
        model = RelativeFreeFieldModel(
            calibration,
            app_config.spatial_field.acoustics,
            0.4,
            10.0,
        )
        levels = model.evaluate(
            np.full((4, 6), 2.0, dtype=np.float32),
            (1280, 720),
        )
        self.assertTrue(np.all(np.isfinite(levels)))


class TemporalDepthStabilizerTests(unittest.TestCase):
    def test_global_scale_drift_is_corrected_in_log_depth(self):
        stabilizer = TemporalDepthStabilizer(
            SpatialDepthTemporalConfig(
                time_constant_s=1.0,
                max_scale_correction_ratio=1.25,
            )
        )
        first = stabilizer.update(np.full((2, 2), 2.0, dtype=np.float32), 0.0)
        second = stabilizer.update(np.full((2, 2), 2.4, dtype=np.float32), 1.0)

        self.assertTrue(np.allclose(first, 2.0))
        self.assertTrue(np.allclose(second, 2.0, atol=1e-5))

    def test_local_change_bypasses_the_temporal_blend(self):
        stabilizer = TemporalDepthStabilizer(
            SpatialDepthTemporalConfig(
                time_constant_s=10.0,
                max_scale_correction_ratio=1.25,
                pixel_gate_ratio=1.25,
            )
        )
        stabilizer.update(np.full((2, 2), 2.0, dtype=np.float32), 0.0)
        stabilized = stabilizer.update(
            np.array([[2.4, 2.4], [2.4, 4.8]], dtype=np.float32),
            0.1,
        )

        self.assertTrue(np.allclose(stabilized[:1, :], 2.0, atol=1e-5))
        self.assertAlmostEqual(float(stabilized[1, 1]), 4.0, places=5)

    def test_long_gap_resets_the_prior(self):
        stabilizer = TemporalDepthStabilizer(
            SpatialDepthTemporalConfig(max_gap_s=0.5)
        )
        stabilizer.update(np.full((2, 2), 2.0, dtype=np.float32), 0.0)
        reset = stabilizer.update(np.full((2, 2), 4.0, dtype=np.float32), 1.0)

        self.assertTrue(np.allclose(reset, 4.0))


class SoundFieldOverlayTests(unittest.TestCase):
    def test_relative_field_blends_onto_the_original_bgr_frame(self):
        frame = np.zeros((32, 48, 3), dtype=np.uint8)
        snapshot = SpatialFieldSnapshot(
            sequence=1,
            frame_id=4,
            captured_at=0.0,
            completed_at=0.1,
            source_size=(48, 32),
            depth_m=np.ones((2, 3), dtype=np.float32),
            intensity_db_relative=np.array(
                [[0.0, -20.0, -40.0], [np.nan, -10.0, -30.0]],
                dtype=np.float32,
            ),
            inference_ms=12.0,
            dropped_frames=0,
            active=True,
            status="运行中",
        )
        rendered = render_sound_field_overlay(frame, snapshot)
        self.assertTrue(np.array_equal(frame, np.zeros_like(frame)))
        self.assertFalse(np.array_equal(frame, rendered))
        self.assertEqual(rendered.shape, frame.shape)

    def test_unavailable_field_adds_no_status_text_to_the_image(self):
        frame = np.full((32, 48, 3), (10, 20, 30), dtype=np.uint8)
        snapshot = SpatialFieldSnapshot(
            sequence=1,
            frame_id=4,
            captured_at=0.0,
            completed_at=0.1,
            source_size=(48, 32),
            depth_m=np.full((2, 3), np.nan, dtype=np.float32),
            intensity_db_relative=np.full((2, 3), np.nan, dtype=np.float32),
            inference_ms=12.0,
            dropped_frames=0,
            active=False,
            status="分析不可用",
        )
        rendered = render_sound_field_overlay(frame, snapshot)
        self.assertTrue(np.array_equal(rendered, frame))


class SpatialFieldServiceTests(unittest.TestCase):
    def test_background_worker_publishes_bounded_map(self):
        app_config = AppConfig()
        spatial_config = replace(
            app_config.spatial_field,
            enabled=True,
            interval_s=0.001,
            result_ttl_s=2.0,
        )
        estimator = _Estimator()
        model = RelativeFreeFieldModel(
            app_config.camera.calibration,
            spatial_config.acoustics,
            spatial_config.depth.min_depth_m,
            spatial_config.depth.max_depth_m,
        )
        service = SpatialFieldService(spatial_config, estimator, model)
        vision = VisionSnapshot(7, time.monotonic(), (1280, 720), ())
        service.start()
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        service.submit(image, vision)
        deadline = time.monotonic() + 1.0
        snapshot = None
        while time.monotonic() < deadline:
            snapshot = service.snapshot()
            if snapshot is not None:
                break
            time.sleep(0.01)
        service.close()

        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot.active)
        self.assertEqual(snapshot.frame_id, 7)
        self.assertEqual(snapshot.depth_m.shape, (180, 320))
        self.assertEqual(snapshot.intensity_db_relative.shape, (180, 320))
        self.assertTrue(np.array_equal(snapshot.source_frame_bgr, image))
        self.assertIsNot(snapshot.source_frame_bgr, image)
        self.assertEqual(estimator.calls, 1)

    def test_disabled_service_never_calls_estimator(self):
        config = AppConfig()
        estimator = _Estimator()
        model = RelativeFreeFieldModel(
            config.camera.calibration,
            config.spatial_field.acoustics,
            0.4,
            10.0,
        )
        service = SpatialFieldService(config.spatial_field, estimator, model)
        service.start()
        service.submit(
            np.zeros((720, 1280, 3), dtype=np.uint8),
            VisionSnapshot(1, time.monotonic(), (1280, 720), ()),
        )
        time.sleep(0.02)
        service.close()
        self.assertEqual(estimator.calls, 0)


class SpatialConfigTests(unittest.TestCase):
    def test_depth_input_dimensions_must_fit_model_stride(self):
        with self.assertRaises(ValueError):
            replace(SpatialFieldConfig().depth, input_width=300)

    def test_temporal_gate_ratio_must_exceed_one(self):
        with self.assertRaises(ValueError):
            SpatialDepthTemporalConfig(pixel_gate_ratio=1.0)


if __name__ == "__main__":
    unittest.main()
