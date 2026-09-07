"""Framework-neutral lifecycle for the two application services."""

from .control_service import ControlService
from .vision_service import VisionService


class ApplicationRuntime:
    def __init__(
        self,
        vision: VisionService,
        control: ControlService,
    ) -> None:
        self.vision = vision
        self.control = control
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.vision.start()
        try:
            self.control.start()
        except Exception:
            self.vision.close()
            raise
        self._started = True

    def close(self) -> None:
        if not self._started:
            return
        self.vision.close()
        self.control.close()
        self._started = False
