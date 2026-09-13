"""Framework-neutral lifecycle for vision, control, audio, and the device link."""

import queue
from dataclasses import replace

from ..domain.intents import (
    ConfigureAudio,
    SelectAudioSource,
    StartAudio,
    StopAudio,
)
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
        self._audio_intents = queue.Queue()

    def submit(self, intent) -> None:
        if isinstance(
            intent, (StartAudio, StopAudio, ConfigureAudio, SelectAudioSource)
        ):
            self._audio_intents.put(intent)
            return
        self.control.submit(intent)

    def tick(self):
        self._drain_audio_intents()
        snapshot = self.control.tick()
        if self.audio is None:
            return snapshot
        return replace(snapshot, audio=self.audio.control_status())

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

    def _drain_audio_intents(self) -> None:
        while True:
            try:
                intent = self._audio_intents.get_nowait()
            except queue.Empty:
                return
            if self.audio is None:
                continue
            try:
                if isinstance(intent, StartAudio):
                    self.audio.start_transmitting()
                elif isinstance(intent, StopAudio):
                    self.audio.stop_transmitting()
                elif isinstance(intent, ConfigureAudio):
                    self.audio.configure(intent.settings)
                elif isinstance(intent, SelectAudioSource):
                    self.audio.select_source(intent.source)
            except Exception as error:  # noqa: BLE001 - user-action boundary
                self.audio.record_error(error)
