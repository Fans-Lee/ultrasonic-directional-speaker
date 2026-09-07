"""Desktop GUI entry point."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .bootstrap import build_application
from .config import load_config


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="视觉云台跟踪系统")
    parser.add_argument(
        "--config",
        type=Path,
        default=_project_root() / "configs" / "vision_gimbal.toml",
    )
    parser.add_argument("--serial-port", default=None)
    parser.add_argument("--baudrate", type=int, default=None)
    parser.add_argument("--camera-index", type=int, default=None)
    parser.add_argument("--device", default=None)
    return parser.parse_args(argv)


def _apply_cli_overrides(config, args):
    camera = config.camera
    vision = config.vision
    serial = config.serial
    if args.camera_index is not None:
        camera = replace(camera, index=args.camera_index)
    if args.device is not None:
        vision = replace(vision, device=args.device)
    if args.serial_port is not None:
        serial = replace(serial, port=args.serial_port or None)
    if args.baudrate is not None:
        serial = replace(serial, baudrate=args.baudrate)
    return replace(config, camera=camera, vision=vision, serial=serial)


def main(argv=None) -> int:
    args = _parse_args(argv)
    qt_app = QApplication.instance() or QApplication(sys.argv[:1])
    try:
        config = _apply_cli_overrides(load_config(args.config), args)
        bundle = build_application(config)
        bundle.window.show()
        bundle.runtime.start()
    except Exception as error:  # noqa: BLE001 - top-level startup boundary
        QMessageBox.critical(None, "视觉云台启动失败", str(error))
        return 1

    print(f"YOLO inference device: {bundle.inference_device}")
    qt_app.aboutToQuit.connect(bundle.runtime.stop)
    result = qt_app.exec()
    bundle.runtime.stop()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
