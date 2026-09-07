"""Read one camera frame and run the complete vision pipeline."""

from dataclasses import dataclass
from typing import Any

from ..domain.tracking import VisionSnapshot
from ..ports.camera import CameraSource
from ..ports.clock import Clock
from ..vision.pipeline import VisionPipeline
from .latest_snapshot import LatestSnapshotStore


class CameraReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DisplayFrame:
    image: Any
    snapshot: VisionSnapshot


class VisionService:
    def __init__(
        self,
        camera: CameraSource,
        pipeline: VisionPipeline,
        clock: Clock,
        snapshots: LatestSnapshotStore[VisionSnapshot],
    ) -> None:
        self.camera = camera
        self.pipeline = pipeline
        self.clock = clock
        self.snapshots = snapshots
        self._frame_id = 0

    def start(self) -> None:
        self.camera.open()

    def step(self) -> DisplayFrame:
        image = self.camera.read()
        if image is None:
            raise CameraReadError("无法从摄像头读取画面")
        self._frame_id += 1
        captured_at = self.clock.now()
        snapshot = self.pipeline.process(
            image,
            self._frame_id,
            captured_at,
        )
        self.snapshots.set(snapshot)
        return DisplayFrame(image=image, snapshot=snapshot)

    def close(self) -> None:
        self.camera.close()
        self.pipeline.reset()
        self.snapshots.clear()
