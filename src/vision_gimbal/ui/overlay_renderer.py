"""Draw tracking metadata without making selection decisions."""

from typing import Optional

import cv2

from ..domain.state import UiSnapshot
from ..domain.tracking import VisionSnapshot


_COLORS = (
    (80, 220, 80),
    (255, 160, 60),
    (80, 180, 255),
    (220, 100, 220),
    (255, 220, 80),
    (200, 200, 200),
)


def _dashed_rectangle(image, top_left, bottom_right, color, thickness=2):
    x1, y1 = top_left
    x2, y2 = bottom_right
    dash = 10
    for x in range(x1, x2, dash * 2):
        cv2.line(image, (x, y1), (min(x + dash, x2), y1), color, thickness)
        cv2.line(image, (x, y2), (min(x + dash, x2), y2), color, thickness)
    for y in range(y1, y2, dash * 2):
        cv2.line(image, (x1, y), (x1, min(y + dash, y2)), color, thickness)
        cv2.line(image, (x2, y), (x2, min(y + dash, y2)), color, thickness)


def render_overlay(
    frame,
    vision: VisionSnapshot,
    state: Optional[UiSnapshot],
):
    annotated = frame.copy()
    selected_id = state.selected_target_id if state is not None else None
    active_id = state.active_target_id if state is not None else None
    for person in vision.tracks:
        x1, y1, x2, y2 = (
            round(value) for value in person.bbox_xyxy
        )
        if person.track_id == active_id:
            color = (0, 255, 255)
            suffix = " TRACKING"
            thickness = 3
        elif person.track_id == selected_id:
            color = (255, 120, 0)
            suffix = " SELECTED"
            thickness = 3
        else:
            color = _COLORS[person.track_id % len(_COLORS)]
            suffix = ""
            thickness = 2
        if person.observed:
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
        else:
            _dashed_rectangle(annotated, (x1, y1), (x2, y2), color, 1)
            suffix += " PREDICTED"
        cv2.putText(
            annotated,
            "ID %s%s" % (person.track_id, suffix),
            (max(0, x1), max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
            cv2.LINE_AA,
        )
        point = tuple(round(value) for value in person.aim_point)
        cv2.drawMarker(annotated, point, color, cv2.MARKER_CROSS, 20, 2)

    if state is not None and state.aim_center is not None:
        center = tuple(round(value) for value in state.aim_center)
        cv2.drawMarker(
            annotated,
            center,
            (0, 0, 255),
            cv2.MARKER_CROSS,
            30,
            2,
        )
    if state is not None and state.telemetry.control_aim_point is not None:
        point = tuple(round(value) for value in state.telemetry.control_aim_point)
        cv2.drawMarker(
            annotated,
            point,
            (255, 0, 255),
            cv2.MARKER_TILTED_CROSS,
            24,
            2,
        )
    return annotated
