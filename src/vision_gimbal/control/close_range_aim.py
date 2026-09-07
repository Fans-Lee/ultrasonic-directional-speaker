"""Near-range upper-body aiming policy."""

from dataclasses import dataclass, replace
from typing import Optional, Tuple

from ..config.schema import CloseRangeConfig
from ..domain.geometry import FrameSize
from ..domain.tracking import TargetObservation


@dataclass(frozen=True)
class CloseRangeStatus:
    active: bool = False
    height_ratio: float = 0.0


class CloseRangeAimPolicy:
    def __init__(self, config: CloseRangeConfig) -> None:
        self.config = config
        self._track_id: Optional[int] = None
        self._active = False
        self._enter_count = 0
        self._exit_count = 0
        self._height_ratio: Optional[float] = None
        self._last_box_height_px = 0.0
        self._last_observation_timestamp = None

    def reset(self) -> None:
        self._track_id = None
        self._active = False
        self._enter_count = 0
        self._exit_count = 0
        self._height_ratio = None
        self._last_box_height_px = 0.0
        self._last_observation_timestamp = None

    def status(self) -> CloseRangeStatus:
        return CloseRangeStatus(
            active=self._active,
            height_ratio=self._height_ratio or 0.0,
        )

    def update(
        self,
        observation: TargetObservation,
        frame_size: FrameSize,
    ) -> Tuple[TargetObservation, CloseRangeStatus]:
        if observation.track_id != self._track_id:
            self.reset()
            self._track_id = observation.track_id

        is_new_observation = (
            observation.timestamp_s != self._last_observation_timestamp
        )
        if observation.observed and is_new_observation:
            self._last_observation_timestamp = observation.timestamp_s
            self._update_state(observation.bbox_xyxy, frame_size)

        adjusted = observation
        if self._active and self._last_box_height_px > 0.0:
            offset_y = (
                self.config.upper_body_fraction - 0.5
            ) * self._last_box_height_px
            adjusted = replace(
                observation,
                aim_point=(
                    observation.aim_point[0],
                    observation.aim_point[1] + offset_y,
                ),
            )
        return adjusted, self.status()

    def _update_state(self, bbox, frame_size: FrameSize) -> None:
        _, frame_height = frame_size
        if frame_height <= 0:
            raise ValueError("frame height must be positive")
        _, y1, _, y2 = bbox
        clipped_y1 = min(max(y1, 0.0), float(frame_height))
        clipped_y2 = min(max(y2, 0.0), float(frame_height))
        box_height = max(0.0, clipped_y2 - clipped_y1)
        ratio = box_height / frame_height
        if self._height_ratio is None:
            self._height_ratio = ratio
        else:
            alpha = self.config.ratio_ema_alpha
            self._height_ratio = (
                alpha * ratio + (1.0 - alpha) * self._height_ratio
            )
        self._last_box_height_px = box_height

        margin_px = frame_height * self.config.border_margin_ratio
        touches_top = y1 <= margin_px
        touches_bottom = y2 >= frame_height - margin_px
        if not self._active:
            entering = (
                self._height_ratio >= self.config.enter_height_ratio
                and (touches_top or touches_bottom)
            )
            self._enter_count = self._enter_count + 1 if entering else 0
            if self._enter_count >= self.config.enter_confirmed_frames:
                self._active = True
                self._exit_count = 0
            return

        exiting = (
            self._height_ratio <= self.config.exit_height_ratio
            and not touches_top
            and not touches_bottom
        )
        self._exit_count = self._exit_count + 1 if exiting else 0
        if self._exit_count >= self.config.exit_confirmed_frames:
            self._active = False
            self._enter_count = 0
