import time
from collections import defaultdict
from threading import Lock


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter for multi-tenant API requests."""

    def __init__(self, default_limit: int = 120, window_seconds: float = 60.0):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(
        self,
        identifier: str,
        limit: int | None = None,
    ) -> tuple[bool, int]:
        """Check if request for identifier is allowed.

        Returns:
            (allowed: bool, retry_after: int)
        """
        max_requests = limit if limit is not None else self.default_limit
        now = time.monotonic()
        window_start = now - self.window_seconds

        with self._lock:
            timestamps = self._history[identifier]
            # Prune timestamps older than window
            valid_timestamps = [t for t in timestamps if t > window_start]

            if len(valid_timestamps) >= max_requests:
                earliest = valid_timestamps[0]
                retry_after = max(1, int(self.window_seconds - (now - earliest) + 1))
                self._history[identifier] = valid_timestamps
                return False, retry_after

            valid_timestamps.append(now)
            self._history[identifier] = valid_timestamps
            return True, 0

    def reset(self, identifier: str | None = None) -> None:
        """Reset history for an identifier or all identifiers."""
        with self._lock:
            if identifier is not None:
                self._history.pop(identifier, None)
            else:
                self._history.clear()


# Default singleton instance for ingestion endpoints
ingest_rate_limiter = SlidingWindowRateLimiter(default_limit=120, window_seconds=60.0)

