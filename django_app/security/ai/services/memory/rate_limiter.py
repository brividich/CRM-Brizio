"""Rate limiter for embedding providers."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter for embedding providers."""

    def __init__(self, requests_per_minute: int = 60):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute.
        """
        self.requests_per_minute = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = False

    def check_and_wait(self) -> bool:
        """
        Check if request is allowed and wait if necessary.

        Returns:
            True if request is allowed, False if rate limit is exceeded.
        """
        now = time.time()

        # Remove timestamps older than 1 minute
        while self._timestamps and self._timestamps[0] < now - 60:
            self._timestamps.popleft()

        # Check if we're at the limit
        if len(self._timestamps) >= self.requests_per_minute:
            logger.warning(
                f"Rate limit exceeded: {len(self._timestamps)} requests in last minute, "
                f"limit is {self.requests_per_minute}"
            )
            return False

        # Record this request
        self._timestamps.append(now)
        return True

    def reset(self) -> None:
        """Reset rate limiter state."""
        self._timestamps.clear()

    def get_remaining(self) -> int:
        """
        Get remaining requests for current minute.

        Returns:
            Number of requests remaining in current minute.
        """
        now = time.time()

        # Remove timestamps older than 1 minute
        while self._timestamps and self._timestamps[0] < now - 60:
            self._timestamps.popleft()

        return max(0, self.requests_per_minute - len(self._timestamps))

    def get_wait_time(self) -> float:
        """
        Get time to wait before next request is allowed.

        Returns:
            Seconds to wait, or 0 if request is allowed immediately.
        """
        if len(self._timestamps) < self.requests_per_minute:
            return 0.0

        # Time until oldest timestamp is 1 minute old
        oldest = self._timestamps[0]
        now = time.time()
        wait_time = max(0.0, oldest + 60 - now)

        return wait_time
