"""Framework-neutral lifecycle for vision, control, audio, and the device link."""

from .control_service import ControlService
from .vision_service import VisionService


class ApplicationRuntime:
    def __init__(
        self,
        vision: VisionService,
        control: ControlService,
        audio=None,
        device_link=None,
    ) -> None:
        self.vision = vision
        self.control = control
        self.audio = audio
        self.device_link = device_link
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        if self.device_link is not None:
            self.device_link.start()
        try:
            self.vision.start()
            self.control.start()
            if self.audio is not None:
                self.audio.start()
        except Exception:
            if self.audio is not None:
                self.audio.close()
            self.control.close()
            self.vision.close()
            if self.device_link is not None:
                self.device_link.close()
            raise
        self._started = True

    def close(self) -> None:
        if not self._started:
            return
        if self.audio is not None:
            self.audio.close()
        self.control.close()
        self.vision.close()
        if self.device_link is not None:
            self.device_link.close()
        self._started = False
