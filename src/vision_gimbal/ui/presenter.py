"""Map domain state to Chinese UI labels and enabled states."""

from ..domain.audio import AudioModeSettings, AudioSourceKind
from ..domain.state import ControlMode, TargetStatus, UiSnapshot
from .view_models import MainWindowViewModel

_TARGET_STATUS_TEXT = {
    TargetStatus.NONE: "未选择",
    TargetStatus.READY: "已选择，等待开始",
    TargetStatus.OBSERVED: "已观测",
    TargetStatus.PREDICTED: "短暂漏检，Kalman 预测",
    TargetStatus.LOST: "目标丢失",
}


def present(snapshot: UiSnapshot) -> MainWindowViewModel:
    automatic = snapshot.control_mode is ControlMode.AUTO_TRACKING
    selected = snapshot.selected_target_id
    active = snapshot.active_target_id
    switching = automatic and selected is not None and selected != active
    if not snapshot.serial.enabled:
        serial_text = "仿真模式（未配置串口）"
        serial_detail = "云台命令只在程序内部计算"
    elif snapshot.serial.connected:
        serial_text = "串口已连接"
        serial_detail = snapshot.serial.last_response or "连接正常"
    else:
        serial_text = "串口重连中"
        serial_detail = snapshot.serial.last_error or "等待设备"

    audio = snapshot.audio
    settings = AudioModeSettings(
        processing=audio.settings.processing,
        drive=audio.settings.drive,
        modulation=audio.settings.modulation,
    )
    telemetry = audio.telemetry
    source_text = {
        AudioSourceKind.MICROPHONE: "麦克风",
        AudioSourceKind.STEREO_MIX: "立体声混音",
        AudioSourceKind.SYSTEM_LOOPBACK: "系统进程回环",
    }[audio.selected_source]
    if not audio.enabled:
        audio_state_text = "配置已禁用"
    elif snapshot.serial.connected and snapshot.serial.volume_supported is False:
        audio_state_text = "固件需更新"
    elif audio.transmitting and snapshot.serial.connected:
        if not audio.source_open:
            audio_state_text = "启动中"
        elif (
            audio.selected_source is AudioSourceKind.SYSTEM_LOOPBACK
            and not audio.array_active
        ):
            audio_state_text = "等待电脑声音"
        else:
            audio_state_text = f"{source_text}传输中"
    elif audio.transmitting:
        audio_state_text = "串口重连中"
    elif snapshot.serial.connected:
        audio_state_text = "已关闭"
    else:
        audio_state_text = "等待串口"
    mode_text = (
        f"{settings.processing.value.upper()} / "
        f"{'BOOST' if settings.drive.value == 'boost' else 'STANDARD'} / "
        f"{'DSB-AM' if settings.modulation.value == 'dsb_am' else 'SRAM'}"
    )
    audio_detail = (
        f"音源 {source_text} · {mode_text} · ESP32 {telemetry.state.name} · "
        f"缓冲 {telemetry.buffer_fill_samples}/{telemetry.buffer_capacity_samples} · "
        f"欠载 {telemetry.underrun_count} · 主机丢包 "
        f"{telemetry.host_tx_overrun_count + telemetry.host_capture_overrun_count}"
    )
    audio_detail += f" · 音量 {audio.volume_percent}%"
    confirmed_volume = telemetry.device_volume_permille
    if snapshot.serial.volume_supported is False:
        audio_detail += "\n当前固件不支持连续音量，请升级固件"
    elif snapshot.serial.connected and confirmed_volume != audio.volume_percent * 10:
        audio_detail += " · 等待音量同步"
    if telemetry.host_capture_restart_count:
        audio_detail += f" · 回环重启 {telemetry.host_capture_restart_count}"
    if audio.last_error:
        audio_detail += f"\n错误：{audio.last_error}"

    return MainWindowViewModel(
        mode_text="自动追踪" if automatic else "停止追踪 / 手动控制",
        selected_target_text=("无" if selected is None else f"ID {selected}"),
        active_target_text="无" if active is None else f"ID {active}",
        target_status_text=_TARGET_STATUS_TEXT[snapshot.target_status],
        pose_text=(
            f"pan {snapshot.last_commanded_pose.pan_degrees:+.1f}°  "
            f"tilt {snapshot.last_commanded_pose.tilt_degrees:+.1f}°"
        ),
        control_source_text=snapshot.control_source.value.upper(),
        serial_text=serial_text,
        serial_detail=serial_detail,
        message=snapshot.message,
        start_button_text="切换目标" if switching else "开始追踪",
        start_enabled=(
            snapshot.selected_target_available
            and selected is not None
            and (not automatic or switching)
        ),
        stop_enabled=automatic,
        manual_enabled=not automatic,
        audio_state_text=audio_state_text,
        audio_detail=audio_detail,
        audio_source=audio.selected_source,
        audio_settings=settings,
        audio_start_enabled=(
            audio.enabled and snapshot.serial.connected
            and snapshot.serial.volume_supported is True
            and not audio.transmitting
        ),
        audio_stop_enabled=audio.transmitting,
        audio_controls_enabled=audio.enabled,
        audio_volume_percent=audio.volume_percent,
        audio_volume_enabled=(
            audio.enabled and snapshot.serial.connected
            and snapshot.serial.volume_supported is True
        ),
    )
