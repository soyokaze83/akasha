"""Google Gemini LLM client with rotating API key support."""

import logging
from typing import Optional

from google.genai import types
from google.genai.errors import ClientError

from src.core.config import settings
from src.llm.key_rotator import gemini_key_rotator

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini LLM with automatic key rotation on errors."""

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
        Generate content using Gemini with automatic key rotation on errors.

        Args:
            prompt: User prompt
            system_instruction: Optional system instruction
            temperature: Creativity level (0.0-1.0)
            max_output_tokens: Maximum tokens in response

        Returns:
            Generated text content

        Raises:
            ClientError: If all API keys are exhausted
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
                error_str = str(e).lower()
                # Check if error warrants trying next key
                is_rotatable_error = (
                    # Rate limit / quota errors
                    "429" in str(e)
                    or "quota" in error_str
                    or "rate" in error_str
                    or "exhausted" in error_str
                    or "all api keys" in error_str
                    # Invalid/expired API key errors
                    or "api_key_invalid" in error_str
                    or "api key expired" in error_str
                    or "invalid_argument" in error_str
                    or "invalid api key" in error_str
                    # SERVER OVERLOAD / UNAVAILABLE ERRORS
                    or "503" in str(e)
                    or "500" in error_str
                    or "unavailable" in error_str
                    or "overload" in error_str
                    or "overloaded" in error_str
                    or "internal error" in error_str
                    or "temporarily unavailable" in error_str
                )

                if is_rotatable_error:
                    last_error = e
                    logger.warning(
                        f"API key {attempt + 1}/{num_keys} failed ({str(e)[:50]}...), rotating..."
                    )
                    self._rotator.rotate()
                else:
                    # Unexpected error, re-raise immediately
                    raise

        # All keys exhausted
        logger.error("All Gemini API keys exhausted")
        raise last_error or ClientError("All API keys exhausted")


# Singleton instance for dependency injection
gemini_client = GeminiClient()
