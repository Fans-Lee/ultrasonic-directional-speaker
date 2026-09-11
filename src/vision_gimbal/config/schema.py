"""Typed configuration for the complete desktop application."""

from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True)
class CameraCalibrationConfig:
    """Intrinsic parameters at the resolution used during calibration."""

    reference_width: int = 1920
    reference_height: int = 1080
    fx: float = 1450.0
    fy: float = 1450.0
    cx: float = 960.0
    cy: float = 540.0
    distortion: tuple[float, float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )

    def __post_init__(self) -> None:
        if self.reference_width <= 0 or self.reference_height <= 0:
            raise ValueError("camera calibration reference dimensions must be positive")
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("camera calibration focal lengths must be positive")
        if not 0.0 <= self.cx <= self.reference_width:
            raise ValueError("camera calibration cx must lie within reference width")
        if not 0.0 <= self.cy <= self.reference_height:
            raise ValueError("camera calibration cy must lie within reference height")
        values = tuple(float(value) for value in self.distortion)
        if len(values) != 5 or not all(isfinite(value) for value in values):
            raise ValueError("camera calibration distortion must contain five finite values")
        object.__setattr__(self, "distortion", values)


@dataclass(frozen=True)
class CameraConfig:
    index: int = 1
    rotation: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    calibration: CameraCalibrationConfig = field(
        default_factory=CameraCalibrationConfig
    )

    def __post_init__(self) -> None:
        if self.rotation not in (0, 180):
            raise ValueError("camera.rotation must be 0 or 180")
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("camera dimensions and fps must be positive")


@dataclass(frozen=True)
class VisionConfig:
    model_path: str = "yolo26s.pt"
    tracker_config_path: str = "configs/bytetrack_person.yaml"
    confidence: float = 0.10
    image_size: int = 512
    nms_iou_threshold: float = 0.60
    duplicate_iou_threshold: float = 0.70
    duplicate_containment_threshold: float = 0.90
    prediction_duplicate_iou_threshold: float = 0.55
    prediction_duplicate_containment_threshold: float = 0.85
    max_prediction_frames: int = 12
    device: str = "auto"

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("vision.confidence must be in [0, 1]")
        if self.image_size <= 0 or self.max_prediction_frames < 0:
            raise ValueError("invalid vision image size or prediction count")
        for name in (
            "nms_iou_threshold",
            "duplicate_iou_threshold",
            "duplicate_containment_threshold",
            "prediction_duplicate_iou_threshold",
            "prediction_duplicate_containment_threshold",
        ):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"vision.{name} must be in (0, 1]")


@dataclass(frozen=True)
class TargetLockConfig:
    min_confidence: float = 0.10
    prediction_timeout_s: float = 0.20
    release_timeout_s: float = 0.80
    max_selection_age_frames: int = 30

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("target.min_confidence must be in [0, 1]")
        if self.prediction_timeout_s < 0.0:
            raise ValueError("target.prediction_timeout_s cannot be negative")
        if self.release_timeout_s < self.prediction_timeout_s:
            raise ValueError("target.release_timeout_s must cover prediction")
        if self.max_selection_age_frames < 0:
            raise ValueError("target.max_selection_age_frames cannot be negative")


@dataclass(frozen=True)
class CameraProjectionConfig:
    horizontal_fov_deg: float = 70.0
    vertical_fov_deg: float = 43.0
    aim_offset_x_px: float = 0.0
    aim_offset_y_px: float = 0.0
    pan_sign: float = -1.0
    tilt_sign: float = -1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.horizontal_fov_deg < 179.0:
            raise ValueError("horizontal_fov_deg must be in (0, 179)")
        if not 0.0 < self.vertical_fov_deg < 179.0:
            raise ValueError("vertical_fov_deg must be in (0, 179)")
        if self.pan_sign == 0.0 or self.tilt_sign == 0.0:
            raise ValueError("projection signs cannot be zero")


@dataclass(frozen=True)
class CloseRangeConfig:
    enter_height_ratio: float = 0.90
    exit_height_ratio: float = 0.70
    upper_body_fraction: float = 0.30
    border_margin_ratio: float = 0.03
    enter_confirmed_frames: int = 5
    exit_confirmed_frames: int = 10
    ratio_ema_alpha: float = 0.40

    def __post_init__(self) -> None:
        if not 0.0 < self.exit_height_ratio < self.enter_height_ratio <= 1.0:
            raise ValueError("close-range thresholds must satisfy 0 < exit < enter")
        if not 0.0 < self.upper_body_fraction <= 0.5:
            raise ValueError("upper_body_fraction must be in (0, 0.5]")
        if not 0.0 <= self.border_margin_ratio < 0.5:
            raise ValueError("border_margin_ratio must be in [0, 0.5)")
        if self.enter_confirmed_frames <= 0 or self.exit_confirmed_frames <= 0:
            raise ValueError("close-range confirmation counts must be positive")
        if not 0.0 < self.ratio_ema_alpha <= 1.0:
            raise ValueError("ratio_ema_alpha must be in (0, 1]")


@dataclass(frozen=True)
class AxisPidConfig:
    kp: float = 1.0
    ki: float = 0.08
    kd: float = 0.0
    deadband_deg: float = 0.6
    integral_limit: float = 10.0
    output_limit_deg_s: float = 25.0

    def __post_init__(self) -> None:
        if min(self.kp, self.ki, self.kd) < 0.0:
            raise ValueError("PID gains cannot be negative")
        if self.deadband_deg < 0.0 or self.integral_limit < 0.0:
            raise ValueError("PID deadband and integral limit cannot be negative")
        if self.output_limit_deg_s <= 0.0:
            raise ValueError("PID output limit must be positive")


def _default_pan_pid() -> AxisPidConfig:
    return AxisPidConfig(output_limit_deg_s=25.0)


def _default_tilt_pid() -> AxisPidConfig:
    return AxisPidConfig(output_limit_deg_s=20.0)


@dataclass(frozen=True)
class AutoControlConfig:
    pan_pid: AxisPidConfig = field(default_factory=_default_pan_pid)
    tilt_pid: AxisPidConfig = field(default_factory=_default_tilt_pid)
    nominal_dt_s: float = 0.10
    maximum_dt_s: float = 0.50

    def __post_init__(self) -> None:
        if self.nominal_dt_s <= 0.0 or self.maximum_dt_s < self.nominal_dt_s:
            raise ValueError("invalid automatic-control time step")


@dataclass(frozen=True)
class ManualControlConfig:
    pan_speed_deg_s: float = 20.0
    tilt_speed_deg_s: float = 16.0
    pan_right_sign: float = -1.0
    tilt_up_sign: float = 1.0

    def __post_init__(self) -> None:
        if self.pan_speed_deg_s <= 0.0 or self.tilt_speed_deg_s <= 0.0:
            raise ValueError("manual speeds must be positive")
        if self.pan_right_sign == 0.0 or self.tilt_up_sign == 0.0:
            raise ValueError("manual direction signs cannot be zero")


@dataclass(frozen=True)
class AxisMotionConfig:
    min_angle_deg: float
    max_angle_deg: float
    max_speed_deg_s: float
    max_accel_deg_s2: float

    def __post_init__(self) -> None:
        if self.min_angle_deg >= self.max_angle_deg:
            raise ValueError("axis minimum angle must be below maximum")
        if self.max_speed_deg_s <= 0.0 or self.max_accel_deg_s2 <= 0.0:
            raise ValueError("axis speed and acceleration limits must be positive")
        if self.min_angle_deg < -90.0 or self.max_angle_deg > 90.0:
            raise ValueError("software angle limits must fit firmware -90..90")


def _default_pan_motion() -> AxisMotionConfig:
    return AxisMotionConfig(-90.0, 90.0, 25.0, 80.0)


def _default_tilt_motion() -> AxisMotionConfig:
    return AxisMotionConfig(-10.0, 75.0, 20.0, 60.0)


@dataclass(frozen=True)
class GimbalMotionConfig:
    pan: AxisMotionConfig = field(default_factory=_default_pan_motion)
    tilt: AxisMotionConfig = field(default_factory=_default_tilt_motion)
    nominal_dt_s: float = 0.10
    maximum_dt_s: float = 0.50

    def __post_init__(self) -> None:
        if self.nominal_dt_s <= 0.0 or self.maximum_dt_s < self.nominal_dt_s:
            raise ValueError("invalid gimbal motion time step")


@dataclass(frozen=True)
class SerialConfig:
    port: str | None = None
    baudrate: int = 460800
    read_timeout_s: float = 0.02
    write_timeout_s: float = 0.10
    reconnect_interval_s: float = 1.0
    startup_delay_s: float = 0.8

    def __post_init__(self) -> None:
        if self.baudrate <= 0:
            raise ValueError("serial.baudrate must be positive")


@dataclass(frozen=True)
class AudioCaptureConfig:
    device: str | int | None = None
    sample_rate: int = 48000
    channels: int = 1
    block_ms: int = 10
    queue_ms: int = 100

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("audio capture rate and channels must be positive")
        if self.block_ms <= 0 or self.queue_ms < self.block_ms:
            raise ValueError("audio capture queue must hold at least one block")


@dataclass(frozen=True)
class AudioDspConfig:
    highpass_hz: float = 250.0
    lowpass_hz: float = 3000.0
    measured_eq_enabled: bool = False
    eq_max_boost_db: float = 6.0
    level_target_dbfs: float = -20.0
    level_max_gain_db: float = 12.0
    level_attack_ms: float = 50.0
    level_release_ms: float = 500.0
    level_freeze_below_dbfs: float = -55.0
    compressor_threshold_dbfs: float = -12.0
    compressor_ratio: float = 3.0
    compressor_attack_ms: float = 10.0
    compressor_release_ms: float = 120.0
    limiter_ceiling_dbfs: float = -1.5

    def __post_init__(self) -> None:
        if not 0.0 < self.highpass_hz < self.lowpass_hz:
            raise ValueError("audio DSP must satisfy 0 < highpass < lowpass")
        if self.eq_max_boost_db < 0.0 or self.level_max_gain_db < 0.0:
            raise ValueError("audio gain limits cannot be negative")
        if self.level_attack_ms <= 0.0 or self.level_release_ms <= 0.0:
            raise ValueError("audio level time constants must be positive")
        if self.compressor_ratio < 1.0:
            raise ValueError("audio compressor ratio must be at least one")
        if self.compressor_attack_ms <= 0.0 or self.compressor_release_ms <= 0.0:
            raise ValueError("audio compressor time constants must be positive")
        if not -12.0 <= self.limiter_ceiling_dbfs < 0.0:
            raise ValueError("audio limiter ceiling must be in [-12, 0) dBFS")


@dataclass(frozen=True)
class AudioStreamConfig:
    sample_rate: int = 8000
    packet_ms: int = 20
    prebuffer_ms: int = 60
    device_buffer_ms: int = 256
    data_timeout_ms: int = 100
    host_queue_packets: int = 8
    processing: str = "raw"
    boost: bool = False
    modulation: str = "dsb_am"

    def __post_init__(self) -> None:
        if self.sample_rate != 8000:
            raise ValueError("protocol version 1 requires an 8000 Hz stream")
        if self.packet_ms <= 0 or self.prebuffer_ms < self.packet_ms:
            raise ValueError("audio prebuffer must hold at least one packet")
        if self.device_buffer_ms < self.prebuffer_ms:
            raise ValueError("device audio buffer must cover the prebuffer")
        if self.data_timeout_ms < self.packet_ms:
            raise ValueError("audio data timeout must cover one packet")
        if self.host_queue_packets <= 0:
            raise ValueError("audio host queue must be positive")
        if not isinstance(self.processing, str) or self.processing.lower() not in {
            "raw",
            "loud",
        }:
            raise ValueError("audio.stream.processing must be raw or loud")
        if not isinstance(self.boost, bool):
            raise ValueError("audio.stream.boost must be true or false")
        if not isinstance(self.modulation, str) or self.modulation.lower().replace(
            "-", "_"
        ) not in {"dsb_am", "sram"}:
            raise ValueError("audio.stream.modulation must be dsb_am or sram")

    @property
    def packet_samples(self) -> int:
        return self.sample_rate * self.packet_ms // 1000

    @property
    def prebuffer_samples(self) -> int:
        return self.sample_rate * self.prebuffer_ms // 1000


@dataclass(frozen=True)
class AudioRecordingConfig:
    enabled: bool = False
    path: str = "output/audio_recordings/post_limiter_{timestamp}.wav"

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("audio recording path cannot be empty")
        if not self.path.lower().endswith(".wav"):
            raise ValueError("audio recording path must end with .wav")


@dataclass(frozen=True)
class AudioSpectrumConfig:
    enabled: bool = True
    window_ms: float = 40.0
    hop_ms: float = 20.0
    history_s: float = 6.0
    refresh_hz: float = 10.0
    min_dbfs: float = -80.0
    max_dbfs: float = 0.0
    queue_blocks: int = 4

    def __post_init__(self) -> None:
        if self.window_ms <= 0.0 or not 0.0 < self.hop_ms <= self.window_ms:
            raise ValueError("audio spectrum must satisfy 0 < hop_ms <= window_ms")
        if self.history_s < self.hop_ms / 1000.0:
            raise ValueError("audio spectrum history must hold at least one hop")
        if not 0.0 < self.refresh_hz <= 30.0:
            raise ValueError("audio spectrum refresh_hz must be in (0, 30]")
        if self.min_dbfs >= self.max_dbfs or self.max_dbfs > 0.0:
            raise ValueError("audio spectrum dBFS range must satisfy min < max <= 0")
        if self.queue_blocks <= 0:
            raise ValueError("audio spectrum queue_blocks must be positive")


@dataclass(frozen=True)
class AudioConfig:
    enabled: bool = False
    auto_start: bool = True
    capture: AudioCaptureConfig = field(default_factory=AudioCaptureConfig)
    dsp: AudioDspConfig = field(default_factory=AudioDspConfig)
    stream: AudioStreamConfig = field(default_factory=AudioStreamConfig)
    recording: AudioRecordingConfig = field(default_factory=AudioRecordingConfig)
    spectrum: AudioSpectrumConfig = field(default_factory=AudioSpectrumConfig)


@dataclass(frozen=True)
class SpatialDepthTemporalConfig:
    """Conservative temporal stabilization for independent depth estimates.

    This filter has no camera-motion estimate, so it only blends pixels that
    already agree after a bounded global scale correction.  Large local
    changes remain responsive instead of becoming depth-map trails.
    """

    enabled: bool = True
    time_constant_s: float = 0.8
    max_gap_s: float = 1.5
    scale_alignment_enabled: bool = True
    min_overlap_ratio: float = 0.35
    max_scale_correction_ratio: float = 1.12
    max_scale_residual_ratio: float = 1.08
    pixel_gate_ratio: float = 1.25

    def __post_init__(self) -> None:
        if self.time_constant_s <= 0.0 or self.max_gap_s <= 0.0:
            raise ValueError("spatial temporal time constants must be positive")
        if not 0.0 < self.min_overlap_ratio <= 1.0:
            raise ValueError("spatial temporal overlap ratio must be in (0, 1]")
        for name in (
            "max_scale_correction_ratio",
            "max_scale_residual_ratio",
            "pixel_gate_ratio",
        ):
            if getattr(self, name) <= 1.0:
                raise ValueError(f"spatial temporal {name} must exceed 1")


@dataclass(frozen=True)
class SpatialDepthConfig:
    """Low-rate dense-depth inference configuration.

    The model is intentionally separate from the primary people-tracking model.
    ``input_height`` includes any letterbox padding required by the model.
    """

    model_path: str = "models/yolo26n-depth_openvino_model"
    backend: str = "openvino"
    device: str = "intel:gpu"
    input_width: int = 320
    input_height: int = 192
    min_depth_m: float = 0.4
    max_depth_m: float = 10.0
    allow_cpu_fallback: bool = False
    temporal: SpatialDepthTemporalConfig = field(
        default_factory=SpatialDepthTemporalConfig
    )

    def __post_init__(self) -> None:
        if self.backend.lower() not in {"openvino", "ultralytics"}:
            raise ValueError("spatial_field.depth.backend must be openvino or ultralytics")
        for name in (
            "input_width",
            "input_height",
        ):
            value = getattr(self, name)
            if value <= 0 or value % 32:
                raise ValueError(f"spatial_field.depth.{name} must be a positive multiple of 32")
        if not 0.0 < self.min_depth_m < self.max_depth_m:
            raise ValueError("spatial field depth range must satisfy 0 < min < max")
        if not self.model_path.strip() or not self.device.strip():
            raise ValueError("spatial depth model path and device cannot be empty")


@dataclass(frozen=True)
class SpatialAcousticsConfig:
    """Parameters for a deliberately conservative relative free-field display."""

    display_floor_db: float = -40.0
    overlay_opacity: float = 0.42
    reference_distance_m: float = 1.0
    beam_half_power_angle_deg: float = 12.0
    air_absorption_db_per_m: float = 0.0
    camera_to_speaker_translation_m: tuple[float, float, float] = (
        0.0,
        0.0,
        0.0,
    )
    camera_to_speaker_rotation_deg: tuple[float, float, float] = (
        0.0,
        0.0,
        0.0,
    )

    def __post_init__(self) -> None:
        if self.display_floor_db >= 0.0:
            raise ValueError("spatial display floor must be negative")
        if not 0.0 <= self.overlay_opacity <= 1.0:
            raise ValueError("spatial overlay opacity must be in [0, 1]")
        if self.reference_distance_m <= 0.0:
            raise ValueError("spatial reference distance must be positive")
        if not 0.0 < self.beam_half_power_angle_deg < 90.0:
            raise ValueError("spatial beam half-power angle must be in (0, 90)")
        if self.air_absorption_db_per_m < 0.0:
            raise ValueError("spatial air absorption cannot be negative")
        for name in (
            "camera_to_speaker_translation_m",
            "camera_to_speaker_rotation_deg",
        ):
            values = tuple(float(value) for value in getattr(self, name))
            if len(values) != 3 or not all(isfinite(value) for value in values):
                raise ValueError(f"spatial {name} must contain three finite values")
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class SpatialFieldConfig:
    """Optional analysis path. It must never feed the tracking control loop."""

    enabled: bool = False
    interval_s: float = 0.5
    result_ttl_s: float = 2.0
    max_consecutive_overruns: int = 3
    max_inference_ms: float = 400.0
    refresh_hz: float = 5.0
    depth: SpatialDepthConfig = field(default_factory=SpatialDepthConfig)
    acoustics: SpatialAcousticsConfig = field(default_factory=SpatialAcousticsConfig)

    def __post_init__(self) -> None:
        if self.interval_s <= 0.0 or self.result_ttl_s < self.interval_s:
            raise ValueError("spatial interval and result TTL are invalid")
        if self.max_consecutive_overruns <= 0 or self.max_inference_ms <= 0.0:
            raise ValueError("spatial overrun limits must be positive")
        if not 0.0 < self.refresh_hz <= 30.0:
            raise ValueError("spatial refresh_hz must be in (0, 30]")


@dataclass(frozen=True)
class RuntimeConfig:
    control_hz: float = 10.0

    def __post_init__(self) -> None:
        if not 0.0 < self.control_hz <= 10.0:
            raise ValueError("runtime.control_hz must be in (0, 10]")


@dataclass(frozen=True)
class UiConfig:
    window_title: str = "视觉云台与超声音频控制系统"
    initial_width: int = 1280
    initial_height: int = 760


@dataclass(frozen=True)
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    target: TargetLockConfig = field(default_factory=TargetLockConfig)
    projection: CameraProjectionConfig = field(default_factory=CameraProjectionConfig)
    close_range: CloseRangeConfig = field(default_factory=CloseRangeConfig)
    automatic: AutoControlConfig = field(default_factory=AutoControlConfig)
    manual: ManualControlConfig = field(default_factory=ManualControlConfig)
    motion: GimbalMotionConfig = field(default_factory=GimbalMotionConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    spatial_field: SpatialFieldConfig = field(default_factory=SpatialFieldConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    ui: UiConfig = field(default_factory=UiConfig)
