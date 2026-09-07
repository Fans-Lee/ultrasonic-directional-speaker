"""Clock boundary so timeout behavior can be tested deterministically."""

from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...
