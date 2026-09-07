"""Camera input boundary."""

from typing import Any, Optional, Protocol


class CameraSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> Optional[Any]: ...

    def close(self) -> None: ...
