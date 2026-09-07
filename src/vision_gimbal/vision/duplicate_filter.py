"""Geometry helpers and duplicate-person suppression."""

from typing import List, Sequence, Tuple

from ..domain.geometry import BoundingBox, Point
from ..domain.tracking import TrackedPerson


def _area(bbox: BoundingBox) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_overlap(a: BoundingBox, b: BoundingBox) -> Tuple[float, float]:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0.0,
        min(ay2, by2) - max(ay1, by1),
    )
    if intersection <= 0.0:
        return 0.0, 0.0
    area_a = _area(a)
    area_b = _area(b)
    union = area_a + area_b - intersection
    iou = intersection / union if union > 0.0 else 0.0
    smaller = min(area_a, area_b)
    containment = intersection / smaller if smaller > 0.0 else 0.0
    return iou, containment


def boxes_are_duplicates(
    a: BoundingBox,
    b: BoundingBox,
    iou_threshold: float,
    containment_threshold: float,
) -> bool:
    iou, containment = bbox_overlap(a, b)
    if iou >= iou_threshold:
        return True
    area_a = _area(a)
    area_b = _area(b)
    if min(area_a, area_b) <= 0.0:
        return False
    area_ratio = max(area_a, area_b) / min(area_a, area_b)
    return containment >= containment_threshold and area_ratio <= 2.0


def shift_bbox(bbox: BoundingBox, old_center: Point, new_center: Point):
    dx = new_center[0] - old_center[0]
    dy = new_center[1] - old_center[1]
    x1, y1, x2, y2 = bbox
    return x1 + dx, y1 + dy, x2 + dx, y2 + dy


def suppress_duplicate_people(
    people: Sequence[TrackedPerson],
    iou_threshold: float,
    containment_threshold: float,
) -> List[TrackedPerson]:
    kept = []
    for person in sorted(people, key=lambda item: item.confidence, reverse=True):
        if any(
            boxes_are_duplicates(
                person.bbox_xyxy,
                other.bbox_xyxy,
                iou_threshold,
                containment_threshold,
            )
            for other in kept
        ):
            continue
        kept.append(person)
    return sorted(kept, key=lambda item: item.track_id)
