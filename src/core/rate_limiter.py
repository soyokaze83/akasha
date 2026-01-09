"""Simple in-memory rate limiter for webhook endpoint."""

import asyncio
import time
from collections import defaultdict

from src.core.config import settings


class RateLimiter:
    """
    Sliding window rate limiter per sender JID.

    Limits requests to prevent DoS attacks on the webhook endpoint.
    """

    def __init__(
        self,
        max_requests: int | None = None,
        window_seconds: int | None = None,
    ):
        self.max_requests = max_requests or settings.rate_limit_requests
        self.window_seconds = window_seconds or settings.rate_limit_window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, sender_jid: str) -> bool:
        """
        Check if a request from sender is allowed.

        Args:
            sender_jid: The sender's JID (e.g., "6289685028129@s.whatsapp.net")

        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds

            # Remove expired timestamps
            self._requests[sender_jid] = [
                ts for ts in self._requests[sender_jid] if ts > cutoff
            ]

            # Check if under limit
            if len(self._requests[sender_jid]) >= self.max_requests:
                return False

            # Record this request
            self._requests[sender_jid].append(now)
            return True

    async def cleanup(self) -> int:
        """
        Remove stale entries from the rate limiter.

        Returns:
            Number of senders cleaned up
        """
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            stale_senders = []

            for sender, timestamps in self._requests.items():
                # Remove expired timestamps
                valid = [ts for ts in timestamps if ts > cutoff]
                if not valid:
                    stale_senders.append(sender)
                else:
                    self._requests[sender] = valid

            for sender in stale_senders:
                del self._requests[sender]

            return len(stale_senders)


# Singleton instance
rate_limiter = RateLimiter()
