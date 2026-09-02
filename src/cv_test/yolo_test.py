"""主程序：注册多人物跟踪配置并启动应用。"""

from pathlib import Path

if __package__:
    from .yolo_tracking_app import TrackingConfig, run_person_tracking
else:
    from yolo_tracking_app import TrackingConfig, run_person_tracking


def main():
    project_root = Path(__file__).resolve().parents[2]
    config = TrackingConfig(
        camera_index=0,       # 外接摄像头常见为 1，请按实际设备修改
        camera_rotation=0,    # 摄像头物理反装时设为 180
        frame_width=1280,
        frame_height=720,
        camera_fps=30,
        model_path=str(project_root / "yolo26n.pt"),
        tracker_config_path=str(
            Path(__file__).resolve().parent
            / "configs"
            / "bytetrack_person.yaml"
        ),
        confidence=0.10,      # 保留低置信度检测供 ByteTrack 二次关联
        image_size=512,
        nms_iou_threshold=0.60,
        duplicate_iou_threshold=0.70,
        duplicate_containment_threshold=0.90,
        prediction_duplicate_iou_threshold=0.55,
        prediction_duplicate_containment_threshold=0.85,
        max_prediction_frames=12,  # 避免旧 ID 的预测框长时间残留
    )
    run_person_tracking(config)


if __name__ == "__main__":
    main()
