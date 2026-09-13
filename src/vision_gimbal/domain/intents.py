"""User intents sent from any presentation adapter."""

from dataclasses import dataclass
from enum import Enum

from .audio import AudioModeSettings, AudioSourceKind


class ManualDirection(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


class UserIntent:
    """Marker base class for commands entering the application layer."""


@dataclass(frozen=True)
class SelectTarget(UserIntent):
    track_id: int
    frame_id: int


@dataclass(frozen=True)
class StartTracking(UserIntent):
    pass


@dataclass(frozen=True)
class StopTracking(UserIntent):
    pass


@dataclass(frozen=True)
class StartAudio(UserIntent):
    pass


@dataclass(frozen=True)
class StopAudio(UserIntent):
    pass


@dataclass(frozen=True)
class ConfigureAudio(UserIntent):
    settings: AudioModeSettings


@dataclass(frozen=True)
class SelectAudioSource(UserIntent):
    source: AudioSourceKind


@dataclass(frozen=True)
class ManualKeyChanged(UserIntent):
    direction: ManualDirection
    pressed: bool


@dataclass(frozen=True)
class ClearManualKeys(UserIntent):
    pass


@dataclass(frozen=True)
class ShutdownRequested(UserIntent):
    pass


Intent = (
    SelectTarget
    | StartTracking
    | StopTracking
    | StartAudio
    | StopAudio
    | ConfigureAudio
    | SelectAudioSource
    | ManualKeyChanged
    | ClearManualKeys
    | ShutdownRequested
)
