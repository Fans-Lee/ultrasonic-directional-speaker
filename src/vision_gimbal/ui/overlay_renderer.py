"""Draw tracking metadata without making selection decisions."""

import cv2
import numpy as np

from ..domain.state import UiSnapshot
from ..domain.spatial_field import SpatialFieldSnapshot
from ..domain.tracking import VisionSnapshot

_COLORS = (
    (80, 220, 80),
    (255, 160, 60),
    (80, 180, 255),
    (220, 100, 220),
    (255, 220, 80),
    (200, 200, 200),
)


def render_sound_field_overlay(
    frame,
    spatial: SpatialFieldSnapshot | None,
):
    """Blend the most recent valid relative field map onto a BGR camera frame.

    Invalid depth samples remain fully transparent. Presentation metadata is
    intentionally kept outside this image so the acoustic view stays uncluttered.
    """
    annotated = frame.copy()
    if spatial is None:
        return annotated

    levels = np.asarray(spatial.intensity_db_relative, dtype=np.float32)
    valid = np.isfinite(levels)
    if spatial.active and np.any(valid):
        height, width = annotated.shape[:2]
        normalized = np.clip(
            (levels - spatial.display_floor_db) / -spatial.display_floor_db,
            0.0,
            1.0,
        )
        palette_input = np.rint(
            np.nan_to_num(normalized, nan=0.0) * 255.0
        ).astype(np.uint8)
        heatmap = cv2.applyColorMap(palette_input, cv2.COLORMAP_TURBO)
        heatmap = cv2.resize(heatmap, (width, height), interpolation=cv2.INTER_LINEAR)
        visible = cv2.resize(
            valid.astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        ).astype(bool)
        blended = cv2.addWeighted(
            annotated,
            1.0 - spatial.overlay_opacity,
            heatmap,
            spatial.overlay_opacity,
            0.0,
        )
        annotated[visible] = blended[visible]
    return annotated


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
    state: UiSnapshot | None,
):
    annotated = frame.copy()
    selected_id = state.selected_target_id if state is not None else None
    active_id = state.active_target_id if state is not None else None
    for person in vision.tracks:
        x1, y1, x2, y2 = (round(value) for value in person.bbox_xyxy)
        if person.person_id is not None and person.person_id == active_id:
            color = (0, 255, 255)
            suffix = " TRACKING"
            thickness = 3
        elif person.person_id is not None and person.person_id == selected_id:
            color = (255, 120, 0)
            suffix = " SELECTED"
            thickness = 3
        else:
            color = _COLORS[(person.person_id or person.track_id) % len(_COLORS)]
            suffix = ""
            thickness = 2
        if person.observed:
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
        else:
            _dashed_rectangle(annotated, (x1, y1), (x2, y2), color, 1)
            suffix += " PREDICTED"
        cv2.putText(
            annotated,
            f"ID {person.person_id if person.person_id is not None else '?'}{suffix}",
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
