"""Camera input boundary."""

from typing import Any, Protocol


class CameraSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> Any | None: ...

    def close(self) -> None: ...
