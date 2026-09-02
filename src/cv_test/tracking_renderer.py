"""多人物轨迹的 OpenCV 可视化。"""

from typing import Iterable, Tuple

import cv2
import numpy as np

if __package__:
    from .tracking_models import TrackedPerson
else:
    from tracking_models import TrackedPerson


_TRACK_COLORS = (
    (80, 220, 80),
    (255, 160, 60),
    (80, 180, 255),
    (220, 100, 220),
    (255, 220, 80),
    (200, 200, 200),
)


def _track_color(track_id: int) -> Tuple[int, int, int]:
    return _TRACK_COLORS[track_id % len(_TRACK_COLORS)]


def _display_bbox(person: TrackedPerson):
    x1, y1, x2, y2 = person.bbox_xyxy
    if not person.observed:
        dx = person.aim_point[0] - person.detection_center[0]
        dy = person.aim_point[1] - person.detection_center[1]
        x1, x2 = x1 + dx, x2 + dx
        y1, y2 = y1 + dy, y2 + dy
    return tuple(round(value) for value in (x1, y1, x2, y2))


def render_tracks(
    frame: np.ndarray,
    people: Iterable[TrackedPerson],
) -> np.ndarray:
    """绘制稳定 ID、人物框、原始中心点和滤波后的瞄准点。"""
    annotated = frame.copy()
    for person in people:
        color = _track_color(person.track_id)
        x1, y1, x2, y2 = _display_bbox(person)
        thickness = 2 if person.observed else 1
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

        state_text = "" if person.observed else " predicted"
        label = f"ID {person.track_id}{state_text}"
        label_y = max(y1 - 8, 20)
        cv2.putText(
            annotated,
            label,
            (max(x1, 0), label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )

        aim_point = tuple(round(value) for value in person.aim_point)
        if person.observed:
            detection_point = tuple(
                round(value) for value in person.detection_center
            )
            cv2.circle(annotated, detection_point, 4, (0, 165, 255), -1)
            cv2.line(annotated, detection_point, aim_point, color, 1)

        cv2.drawMarker(
            annotated,
            aim_point,
            color,
            cv2.MARKER_CROSS,
            24,
            2,
        )
    return annotated
