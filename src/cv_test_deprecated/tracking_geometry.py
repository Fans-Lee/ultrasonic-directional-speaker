"""人物跟踪后处理使用的边界框几何函数。"""

from typing import Tuple

if __package__:
    from .tracking_models import BoundingBox, Point
else:
    from tracking_models import BoundingBox, Point


def _area(bbox: BoundingBox) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_overlap(a: BoundingBox, b: BoundingBox) -> Tuple[float, float]:
    """返回 IoU 和较小框被覆盖的比例。"""
    intersection_width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    intersection_height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = intersection_width * intersection_height
    if intersection <= 0.0:
        return 0.0, 0.0

    area_a = _area(a)
    area_b = _area(b)
    union = area_a + area_b - intersection
    smaller_area = min(area_a, area_b)
    iou = intersection / union if union > 0.0 else 0.0
    containment = intersection / smaller_area if smaller_area > 0.0 else 0.0
    return iou, containment


def boxes_are_duplicates(
    a: BoundingBox,
    b: BoundingBox,
    iou_threshold: float,
    containment_threshold: float,
    contained_area_ratio_threshold: float = 0.50,
) -> bool:
    """判断两个框是否很可能描述同一个人物。

    包含率只用于尺寸相近的框，避免把位于前景人物框内部的远处人物误删。
    """
    iou, containment = bbox_overlap(a, b)
    area_a = _area(a)
    area_b = _area(b)
    larger_area = max(area_a, area_b)
    area_ratio = min(area_a, area_b) / larger_area if larger_area > 0.0 else 0.0
    return iou >= iou_threshold or (
        containment >= containment_threshold
        and area_ratio >= contained_area_ratio_threshold
    )


def shift_bbox(
    bbox: BoundingBox,
    from_point: Point,
    to_point: Point,
) -> BoundingBox:
    """按照中心点位移平移边界框。"""
    dx = to_point[0] - from_point[0]
    dy = to_point[1] - from_point[1]
    x1, y1, x2, y2 = bbox
    return x1 + dx, y1 + dy, x2 + dx, y2 + dy
