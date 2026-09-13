"""Ultralytics adapter for a separately deployed YOLO26 depth model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ..config.schema import SpatialDepthConfig


class UltralyticsDepthEstimator:
    """Load the optional model only inside the background analysis worker."""

    def __init__(self, config: SpatialDepthConfig, model: Any = None) -> None:
        self.config = config
        self._model = model

    def estimate(self, image: Any) -> NDArray[np.float32]:
        model = self._ensure_model()
        results = model.predict(
            source=image,
            imgsz=(self.config.input_height, self.config.input_width),
            device=self.config.device,
            verbose=False,
        )
        if not results or getattr(results[0], "depth", None) is None:
            raise RuntimeError("YOLO depth model did not return a depth map")
        value = results[0].depth.data
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        depth = np.asarray(value, dtype=np.float32).squeeze()
        if depth.ndim != 2:
            raise RuntimeError("YOLO depth model returned an invalid depth map shape")
        return depth

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        model_path = Path(self.config.model_path)
        if not model_path.exists():
            raise RuntimeError(
                "spatial depth model is missing: "
                f"{model_path}. Export yolo26n-depth.pt to OpenVINO first."
            )
        if self.config.backend.lower() == "openvino":
            self._require_openvino_accelerator()
        from ultralytics import YOLO

        self._model = YOLO(str(model_path), task="depth")
        return self._model

    def _require_openvino_accelerator(self) -> None:
        try:
            from openvino import Core
        except ImportError as error:
            raise RuntimeError(
                "OpenVINO is required for spatial depth. Install the 'spatial' extra."
            ) from error
        device = self.config.device.lower()
        if device in {"cpu", "intel:cpu"}:
            if not self.config.allow_cpu_fallback:
                raise RuntimeError("CPU fallback is disabled for spatial depth")
            return
        available = {name.split(".", 1)[0].upper() for name in Core().available_devices}
        expected = "GPU" if "gpu" in device else "NPU" if "npu" in device else None
        if expected is not None and expected not in available:
            names = ", ".join(sorted(available)) or "none"
            raise RuntimeError(
                f"requested OpenVINO {expected} is unavailable; detected: {names}"
            )
