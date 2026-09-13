"""Values formatted specifically for widgets."""

from dataclasses import dataclass

from ..domain.audio import AudioModeSettings, AudioSourceKind


@dataclass(frozen=True)
class MainWindowViewModel:
    mode_text: str
    selected_target_text: str
    active_target_text: str
    target_status_text: str
    pose_text: str
    control_source_text: str
    serial_text: str
    serial_detail: str
    message: str
    start_button_text: str
    start_enabled: bool
    stop_enabled: bool
    manual_enabled: bool
    audio_state_text: str
    audio_detail: str
    audio_source: AudioSourceKind
    audio_settings: AudioModeSettings
    audio_start_enabled: bool
    audio_stop_enabled: bool
    audio_controls_enabled: bool
