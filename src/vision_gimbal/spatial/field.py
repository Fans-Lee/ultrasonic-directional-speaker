"""Camera projection and bounded relative free-field calculation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from ..config.schema import CameraCalibrationConfig, SpatialAcousticsConfig


@dataclass(frozen=True)
class CameraIntrinsics:
    """Intrinsics expressed at a particular source-frame resolution."""

    fx: float
    fy: float
    cx: float
    cy: float
    frame_width: int
    frame_height: int

    @classmethod
    def from_calibration(
        cls,
        config: CameraCalibrationConfig,
        frame_size: tuple[int, int],
    ) -> "CameraIntrinsics":
        width, height = frame_size
        if width <= 0 or height <= 0:
            raise ValueError("source frame dimensions must be positive")
        scale_x = width / config.reference_width
        scale_y = height / config.reference_height
        return cls(
            fx=config.fx * scale_x,
            fy=config.fy * scale_y,
            cx=config.cx * scale_x,
            cy=config.cy * scale_y,
            frame_width=width,
            frame_height=height,
        )


def _rotation_matrix_xyz(degrees: tuple[float, float, float]) -> NDArray[np.float32]:
    """Return a camera-to-speaker rotation for intrinsic X, Y, Z Euler angles."""
    x, y, z = (math.radians(value) for value in degrees)
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    rx = np.array(((1, 0, 0), (0, cx, -sx), (0, sx, cx)), dtype=np.float32)
    ry = np.array(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy)), dtype=np.float32)
    rz = np.array(((cz, -sz, 0), (sz, cz, 0), (0, 0, 1)), dtype=np.float32)
    return rz @ ry @ rx


class RelativeFreeFieldModel:
    """Simulate visible-surface direct sound using a Gaussian beam envelope.

    This is deliberately a relative display model. It assumes the speaker's
    forward axis is +Z in its local frame and excludes reflections, diffraction,
    nonlinear parametric generation, and calibrated SPL.
    """

    def __init__(
        self,
        calibration: CameraCalibrationConfig,
        acoustics: SpatialAcousticsConfig,
        min_depth_m: float,
        max_depth_m: float,
    ) -> None:
        self.calibration = calibration
        self.acoustics = acoustics
        self.min_depth_m = min_depth_m
        self.max_depth_m = max_depth_m
        self._rotation = _rotation_matrix_xyz(
            acoustics.camera_to_speaker_rotation_deg
        )
        self._translation = np.asarray(
            acoustics.camera_to_speaker_translation_m,
            dtype=np.float32,
        ).reshape(3, 1)
        self._half_power_radians = math.radians(
            acoustics.beam_half_power_angle_deg
        )

    def evaluate(
        self,
        depth_m: NDArray[np.float32],
        source_size: tuple[int, int],
    ) -> NDArray[np.float32]:
        """Return dB-relative intensity aligned with the low-resolution depth map."""
        depth = np.asarray(depth_m, dtype=np.float32)
        if depth.ndim != 2 or depth.size == 0:
            raise ValueError("depth map must be a non-empty two-dimensional matrix")
        source_width, source_height = source_size
        intrinsics = CameraIntrinsics.from_calibration(
            self.calibration,
            source_size,
        )
        height, width = depth.shape
        xs = (np.arange(width, dtype=np.float32) + 0.5) * source_width / width - 0.5
        ys = (np.arange(height, dtype=np.float32) + 0.5) * source_height / height - 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)

        valid = np.isfinite(depth)
        valid &= depth >= self.min_depth_m
        valid &= depth <= self.max_depth_m
        output = np.full(depth.shape, np.nan, dtype=np.float32)
        if not np.any(valid):
            return output

        z = depth[valid]
        if any(self.calibration.distortion):
            points = np.column_stack((grid_x[valid], grid_y[valid])).reshape(
                -1,
                1,
                2,
            )
            matrix = np.array(
                (
                    (intrinsics.fx, 0.0, intrinsics.cx),
                    (0.0, intrinsics.fy, intrinsics.cy),
                    (0.0, 0.0, 1.0),
                ),
                dtype=np.float32,
            )
            normalized = cv2.undistortPoints(
                points,
                matrix,
                np.asarray(self.calibration.distortion, dtype=np.float32),
            ).reshape(-1, 2)
            x_camera = normalized[:, 0] * z
            y_camera = normalized[:, 1] * z
        else:
            x_camera = (grid_x[valid] - intrinsics.cx) * z / intrinsics.fx
            y_camera = (grid_y[valid] - intrinsics.cy) * z / intrinsics.fy
        points_camera = np.vstack((x_camera, y_camera, z))
        points_speaker = self._rotation @ points_camera + self._translation
        distance = np.linalg.norm(points_speaker, axis=0)
        forward = np.divide(
            points_speaker[2],
            distance,
            out=np.zeros_like(distance),
            where=distance > 1e-6,
        )
        angle = np.arccos(np.clip(forward, -1.0, 1.0))
        directivity = np.exp(
            -math.log(2.0) * (angle / self._half_power_radians) ** 2
        )
        distance_limited = np.maximum(distance, self.acoustics.reference_distance_m)
        relative_intensity = directivity * (
            self.acoustics.reference_distance_m / distance_limited
        ) ** 2
        values = 10.0 * np.log10(np.maximum(relative_intensity, 1e-12))
        values -= self.acoustics.air_absorption_db_per_m * np.maximum(
            distance - self.acoustics.reference_distance_m,
            0.0,
        )
        output[valid] = np.clip(
            values,
            self.acoustics.display_floor_db,
            0.0,
        ).astype(np.float32)
        return output
