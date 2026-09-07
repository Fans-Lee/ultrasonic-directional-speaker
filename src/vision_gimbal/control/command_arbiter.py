"""Select exactly one motion source for each control tick."""

from ..domain.control import ControlDecision, ControlSource, MotionRequest
from ..domain.state import ControlMode


class CommandArbiter:
    def choose(
        self,
        mode: ControlMode,
        auto_request: MotionRequest | None,
        manual_request: MotionRequest,
    ) -> ControlDecision:
        if mode is ControlMode.AUTO_TRACKING and auto_request is not None:
            return ControlDecision(ControlSource.AUTO, auto_request)
        if mode is ControlMode.STOPPED_MANUAL and manual_request.moving:
            return ControlDecision(ControlSource.MANUAL, manual_request)
        return ControlDecision(ControlSource.HOLD, MotionRequest())
