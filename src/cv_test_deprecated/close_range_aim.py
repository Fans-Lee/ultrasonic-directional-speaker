"""Near-range upper-body aiming policy for oversized person boxes."""

from dataclasses import dataclass, replace
from typing import Optional, Tuple

if __package__:
    from .control_models import AimObservation
else:
    from control_models import AimObservation


@dataclass(frozen=True)
class CloseRangeAimConfig:
    """Hysteresis and target-point parameters for close-range framing."""

    enter_height_ratio: float = 0.90
    exit_height_ratio: float = 0.70
    upper_body_fraction: float = 0.30
    border_margin_ratio: float = 0.03
    enter_confirmed_frames: int = 5
    exit_confirmed_frames: int = 10
    ratio_ema_alpha: float = 0.40

    def __post_init__(self) -> None:
        if not 0.0 < self.exit_height_ratio < self.enter_height_ratio <= 1.0:
            raise ValueError(
                "height thresholds must satisfy 0 < exit < enter <= 1"
            )
        if not 0.0 < self.upper_body_fraction <= 0.5:
            raise ValueError("upper_body_fraction must be in (0, 0.5]")
        if not 0.0 <= self.border_margin_ratio < 0.5:
            raise ValueError("border_margin_ratio must be in [0, 0.5)")
        if self.enter_confirmed_frames <= 0 or self.exit_confirmed_frames <= 0:
            raise ValueError("confirmation frame counts must be positive")
        if not 0.0 < self.ratio_ema_alpha <= 1.0:
            raise ValueError("ratio_ema_alpha must be in (0, 1]")


@dataclass(frozen=True)
class CloseRangeAimStatus:
    active: bool = False
    height_ratio: float = 0.0


class CloseRangeAimPolicy:
    """Use a person's upper body instead of its center when it fills the view."""

    def __init__(self, config: CloseRangeAimConfig) -> None:
        self.config = config
        self._track_id: Optional[int] = None
        self._active = False
        self._enter_count = 0
        self._exit_count = 0
        self._height_ratio: Optional[float] = None
        self._last_box_height_px = 0.0

    def reset(self) -> None:
        self._track_id = None
        self._active = False
        self._enter_count = 0
        self._exit_count = 0
        self._height_ratio = None
        self._last_box_height_px = 0.0

    def status(self) -> CloseRangeAimStatus:
        return CloseRangeAimStatus(
            active=self._active,
            height_ratio=self._height_ratio or 0.0,
        )

    def update(
        self,
        observation: AimObservation,
        frame_size: Tuple[int, int],
    ) -> Tuple[AimObservation, CloseRangeAimStatus]:
        if observation.track_id != self._track_id:
            self.reset()
            self._track_id = observation.track_id

        if observation.observed and observation.bbox_xyxy is not None:
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

    def _update_state(
        self,
        bbox_xyxy: Tuple[float, float, float, float],
        frame_size: Tuple[int, int],
    ) -> None:
        _, frame_height = frame_size
        if frame_height <= 0:
            raise ValueError("frame height must be positive")

        _, y1, _, y2 = bbox_xyxy
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
            enters_close_range = (
                self._height_ratio >= self.config.enter_height_ratio
                and (touches_top or touches_bottom)
            )
            self._enter_count = self._enter_count + 1 if enters_close_range else 0
            if self._enter_count >= self.config.enter_confirmed_frames:
                self._active = True
                self._exit_count = 0
            return

        can_exit_close_range = (
            self._height_ratio <= self.config.exit_height_ratio
            and not touches_top
            and not touches_bottom
        )
        self._exit_count = self._exit_count + 1 if can_exit_close_range else 0
        if self._exit_count >= self.config.exit_confirmed_frames:
            self._active = False
            self._enter_count = 0

