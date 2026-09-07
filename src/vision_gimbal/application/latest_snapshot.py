"""A thread-safe single-slot store that never queues stale frames."""

import threading
from typing import Generic, Optional, TypeVar


T = TypeVar("T")


class LatestSnapshotStore(Generic[T]):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: Optional[T] = None

    def set(self, value: T) -> None:
        with self._lock:
            self._value = value

    def get(self) -> Optional[T]:
        with self._lock:
            return self._value

    def clear(self) -> None:
        with self._lock:
            self._value = None
