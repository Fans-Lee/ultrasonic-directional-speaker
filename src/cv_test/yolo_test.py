"""Compatibility entry point for the layered PySide6 application."""

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.main import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
