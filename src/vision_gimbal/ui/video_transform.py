"""Pure aspect-fit coordinate conversion and person hit testing."""

from collections.abc import Iterable
from dataclasses import dataclass

from ..domain.geometry import FrameSize, Point
from ..domain.tracking import TrackedPerson


@dataclass(frozen=True)
class DisplayRect:
    x: float
    y: float
    width: float
    height: float


def aspect_fit_rect(
    source_size: FrameSize,
    widget_size: FrameSize,
) -> DisplayRect:
    source_width, source_height = source_size
    widget_width, widget_height = widget_size
    if min(source_width, source_height, widget_width, widget_height) <= 0:
        return DisplayRect(0.0, 0.0, 0.0, 0.0)
    scale = min(
        widget_width / source_width,
        widget_height / source_height,
    )
    width = source_width * scale
    height = source_height * scale
    return DisplayRect(
        (widget_width - width) / 2.0,
        (widget_height - height) / 2.0,
        width,
        height,
    )


def widget_to_source(
    point: Point,
    source_size: FrameSize,
    widget_size: FrameSize,
) -> Point | None:
    rect = aspect_fit_rect(source_size, widget_size)
    if rect.width <= 0.0 or rect.height <= 0.0:
        return None
    x, y = point
    if not (rect.x <= x <= rect.x + rect.width and rect.y <= y <= rect.y + rect.height):
        return None
    source_width, source_height = source_size
    return (
        (x - rect.x) * source_width / rect.width,
        (y - rect.y) * source_height / rect.height,
    )


def hit_test_track(
    source_point: Point,
    tracks: Iterable[TrackedPerson],
) -> int | None:
    x, y = source_point
    candidates = []
    for track in tracks:
        x1, y1, x2, y2 = track.bbox_xyxy
        if track.observed and x1 <= x <= x2 and y1 <= y <= y2:
            area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            candidates.append((area, -track.confidence, track.track_id))
    return min(candidates)[2] if candidates else None


def select_track_at(
    widget_point: Point,
    source_size: FrameSize,
    widget_size: FrameSize,
    tracks: Iterable[TrackedPerson],
) -> int | None:
    source_point = widget_to_source(widget_point, source_size, widget_size)
    if source_point is None:
        return None
    return hit_test_track(source_point, tracks)
