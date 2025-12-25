"""Google Gemini LLM client."""

import logging
from typing import Optional

from google import genai
from google.genai import types

from src.core.config import settings

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini LLM."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        """Lazy initialization of Gemini client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.8,
        max_output_tokens: int = 4000,
    ) -> str:
        """
        Generate content using Gemini.

        Args:
            prompt: User prompt
            system_instruction: Optional system instruction
            temperature: Creativity level (0.0-1.0)
            max_output_tokens: Maximum tokens in response

        Returns:
            Generated text content
        """
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        logger.debug(f"Generated content with {len(response.text)} characters")
        return response.text


# Singleton instance for dependency injection
gemini_client = GeminiClient()
