"""Map domain state to Chinese UI labels and enabled states."""

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
    )
