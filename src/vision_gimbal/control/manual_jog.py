"""Translate semantic WASD directions into gimbal velocity."""

from typing import AbstractSet

from ..config.schema import ManualControlConfig
from ..domain.control import MotionRequest
from ..domain.intents import ManualDirection


class ManualJogController:
    def __init__(self, config: ManualControlConfig) -> None:
        self.config = config

    def request(
        self,
        directions: AbstractSet[ManualDirection],
    ) -> MotionRequest:
        horizontal = int(ManualDirection.RIGHT in directions) - int(
            ManualDirection.LEFT in directions
        )
        vertical = int(ManualDirection.UP in directions) - int(
            ManualDirection.DOWN in directions
        )
        return MotionRequest(
            pan_velocity_deg_s=(
                horizontal
                * self.config.pan_speed_deg_s
                * self.config.pan_right_sign
            ),
            tilt_velocity_deg_s=(
                vertical
                * self.config.tilt_speed_deg_s
                * self.config.tilt_up_sign
            ),
        )
