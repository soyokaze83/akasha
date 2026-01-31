"""OpenRouter LLM client for fallback provider (text-only, no vision)."""

import logging
from typing import Optional

from openai import AsyncOpenAI

from src.core.config import settings

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """Client for OpenRouter LLM (text-only fallback, no vision support)."""

    def __init__(self):
        self.model = settings.openrouter_model
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenRouter client."""
        if self._client is None:
            if not settings.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY is not configured")
            self._client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key,
            )
        return self._client

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.8,
        max_output_tokens: int = 2000,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> str:
        """
        Generate content using OpenRouter (text-only).

        Args:
            prompt: User prompt (text only, no image support)
            system_instruction: Optional system instruction
            temperature: Creativity level (0.0-2.0)
            max_output_tokens: Maximum tokens in response
            image_data: Ignored - OpenRouter does not support vision
            image_mime_type: Ignored - OpenRouter does not support vision

        Returns:
            Generated text content
        """
        # Log warning if image was provided (will be ignored)
        if image_data:
            logger.warning(
                "OpenRouter does not support vision - image data will be ignored. "
                "Consider using Gemini or OpenAI for multimodal queries."
            )

        messages = []

        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_output_tokens,
        )

        return response.choices[0].message.content or ""


# Singleton instance
openrouter_client = OpenRouterClient()
