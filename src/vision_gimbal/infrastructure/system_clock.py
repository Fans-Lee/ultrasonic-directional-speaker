"""Production monotonic clock."""

import time


class SystemClock:
    def now(self) -> float:
        return time.monotonic()
