"""API key rotation utility for handling rate limits."""

import logging
import threading
from typing import Optional

from google import genai

from src.core.config import settings

logger = logging.getLogger(__name__)


class GeminiKeyRotator:
    """
    Rotating API key manager for Gemini.

    Cycles through multiple API keys to distribute load and avoid rate limits.
    Thread-safe for concurrent access.
    """

    def __init__(self, api_keys: Optional[list[str]] = None):
        self._keys = api_keys or settings.gemini_api_keys
        if not self._keys:
            raise ValueError("No Gemini API keys configured")

        self._current_index = 0
        self._lock = threading.Lock()
        self._clients: dict[str, genai.Client] = {}

        logger.info(f"GeminiKeyRotator initialized with {len(self._keys)} API key(s)")

    @property
    def current_key(self) -> str:
        """Get the current API key."""
        with self._lock:
            return self._keys[self._current_index]

    def rotate(self) -> str:
        """
        Rotate to the next API key.

        Returns:
            The new current API key
        """
        with self._lock:
            old_index = self._current_index
            self._current_index = (self._current_index + 1) % len(self._keys)
            logger.debug(
                f"Rotated API key from index {old_index} to {self._current_index}"
            )
            return self._keys[self._current_index]

    def get_client(self) -> genai.Client:
        """
        Get a Gemini client for the current API key.

        Clients are cached per key to avoid recreation overhead.
        """
        key = self.current_key
        if key not in self._clients:
            self._clients[key] = genai.Client(api_key=key)
        return self._clients[key]

    def get_next_client(self) -> genai.Client:
        """
        Rotate to next key and get its client.

        Use this after hitting a rate limit.
        """
        self.rotate()
        return self.get_client()


# Singleton instance
gemini_key_rotator = GeminiKeyRotator()
