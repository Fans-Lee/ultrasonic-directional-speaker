"""Detector/tracker boundary used by the vision pipeline."""

from collections.abc import Sequence
from typing import Any, Protocol

from ..domain.tracking import TrackedPerson


class PeopleTracker(Protocol):
    def update(self, frame: Any) -> Sequence[TrackedPerson]: ...

    def reset(self) -> None: ...
