"""OpenCV USB camera adapter."""

import cv2

from ..config.schema import CameraConfig


class OpenCVCamera:
    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self._capture = None

    def open(self) -> None:
        capture = cv2.VideoCapture(self.config.index, cv2.CAP_DSHOW)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        capture.set(cv2.CAP_PROP_FPS, self.config.fps)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"无法打开摄像头：index={self.config.index}")
        self._capture = capture

    def read(self) -> object | None:
        if self._capture is None:
            raise RuntimeError("camera is not open")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            return None
        if self.config.rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
