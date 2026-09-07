"""Detector/tracker boundary used by the vision pipeline."""

from typing import Any, Protocol, Sequence

from ..domain.tracking import TrackedPerson


class PeopleTracker(Protocol):
    def update(self, frame: Any) -> Sequence[TrackedPerson]: ...

    def reset(self) -> None: ...
