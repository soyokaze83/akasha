"""In-memory message cache for building reply chain context."""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Same TTL as other caches in main.py
MESSAGE_CACHE_TTL = 86400  # 24 hours


@dataclass
class CachedMessage:
    """A cached message entry."""

    text: str
    sender: str
    replied_id: str
    timestamp: float = field(default_factory=time.time)


class MessageCache:
    """
    In-memory cache for message content, enabling reply chain construction.

    Messages are cached as they flow through webhooks. When a user replies
    in a thread, the cache walks the replied_id links backwards to build
    the full conversation context.
    """

    def __init__(self) -> None:
        self._cache: dict[str, CachedMessage] = {}

    def store(
        self,
        message_id: str,
        text: str,
        sender: str,
        replied_id: str = "",
    ) -> None:
        """Cache a message."""
        self._cache[message_id] = CachedMessage(
            text=text,
            sender=sender,
            replied_id=replied_id,
        )

    def get(self, message_id: str) -> CachedMessage | None:
        """Look up a cached message by ID."""
        return self._cache.get(message_id)

    def build_reply_chain(
        self,
        start_replied_id: str,
        max_depth: int = 10,
        max_total_chars: int = 3000,
    ) -> list[CachedMessage]:
        """
        Walk the reply chain backwards from start_replied_id, then return
        messages in chronological order.

        Args:
            start_replied_id: The replied_id to start walking from
            max_depth: Maximum number of messages to walk back
            max_total_chars: Stop if total text length exceeds this

        Returns:
            List of CachedMessage in chronological order (oldest first),
            or empty list if start_replied_id is not in cache.
        """
        chain: list[CachedMessage] = []
        current_id = start_replied_id
        total_chars = 0

        for _ in range(max_depth):
            msg = self._cache.get(current_id)
            if not msg:
                break

            total_chars += len(msg.text)
            if total_chars > max_total_chars and chain:
                break

            chain.append(msg)

            if not msg.replied_id:
                break
            current_id = msg.replied_id

        chain.reverse()
        return chain

    def format_chain(self, chain: list[CachedMessage]) -> str:
        """Format a reply chain as readable context lines."""
        return "\n".join(f"[{msg.sender}]: {msg.text}" for msg in chain)

    def cleanup(self) -> int:
        """Remove entries older than TTL. Returns count of removed entries."""
        cutoff = time.time() - MESSAGE_CACHE_TTL
        expired = [k for k, v in self._cache.items() if v.timestamp < cutoff]
        for k in expired:
            del self._cache[k]
        return len(expired)


# Singleton instance
message_cache = MessageCache()
