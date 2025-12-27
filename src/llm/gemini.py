"""Google Gemini LLM client with rotating API key support."""

import logging
from typing import Optional

from google.genai import types
from google.genai.errors import ClientError

from src.core.config import settings
from src.llm.key_rotator import gemini_key_rotator

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini LLM with automatic key rotation on rate limits."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.gemini_model
        self._rotator = gemini_key_rotator

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.8,
        max_output_tokens: int = 4000,
    ) -> str:
        """
        Generate content using Gemini with automatic key rotation on rate limits.

        Args:
            prompt: User prompt
            system_instruction: Optional system instruction
            temperature: Creativity level (0.0-1.0)
            max_output_tokens: Maximum tokens in response

        Returns:
            Generated text content

        Raises:
            ClientError: If all API keys are rate limited
        """
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        # Try each key once before giving up
        num_keys = len(self._rotator._keys)
        last_error: Optional[Exception] = None

        for attempt in range(num_keys):
            client = self._rotator.get_client()
            try:
                response = await client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )

                logger.debug(f"Generated content with {len(response.text)} characters")
                return response.text

            except ClientError as e:
                # Check if it's a rate limit error (HTTP 429)
                if "429" in str(e) or "quota" in str(e).lower():
                    last_error = e
                    logger.warning(
                        f"Rate limit hit on API key {attempt + 1}/{num_keys}, rotating..."
                    )
                    self._rotator.rotate()
                else:
                    # Non-rate-limit error, re-raise immediately
                    raise

        # All keys exhausted
        logger.error("All Gemini API keys are rate limited")
        raise last_error or ClientError("All API keys rate limited")


# Singleton instance for dependency injection
gemini_client = GeminiClient()
