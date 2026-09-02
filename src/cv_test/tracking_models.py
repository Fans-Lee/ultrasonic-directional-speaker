"""多人物跟踪层使用的稳定数据结构。"""

from dataclasses import dataclass
from typing import Tuple


Point = Tuple[float, float]
BoundingBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class TrackedPerson:
    """一条人物轨迹在当前帧中的输出。"""

    track_id: int
    bbox_xyxy: BoundingBox
    detection_center: Point
    aim_point: Point
    confidence: float
    observed: bool = True
