"""Typed configuration for the complete desktop application."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CameraConfig:
    index: int = 1
    rotation: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30

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

    @property
    def packet_samples(self) -> int:
        return self.sample_rate * self.packet_ms // 1000

    @property
    def prebuffer_samples(self) -> int:
        return self.sample_rate * self.prebuffer_ms // 1000


@dataclass(frozen=True)
class AudioConfig:
    enabled: bool = False
    auto_start: bool = True
    capture: AudioCaptureConfig = field(default_factory=AudioCaptureConfig)
    dsp: AudioDspConfig = field(default_factory=AudioDspConfig)
    stream: AudioStreamConfig = field(default_factory=AudioStreamConfig)


@dataclass(frozen=True)
class RuntimeConfig:
    control_hz: float = 10.0

    def __post_init__(self) -> None:
        if not 0.0 < self.control_hz <= 10.0:
            raise ValueError("runtime.control_hz must be in (0, 10]")


@dataclass(frozen=True)
class UiConfig:
    window_title: str = "视觉云台跟踪系统"
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
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    ui: UiConfig = field(default_factory=UiConfig)
