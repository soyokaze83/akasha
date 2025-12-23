"""OpenAI LLM client."""

import logging
from typing import Optional

from openai import AsyncOpenAI

from src.core.config import settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    """Client for OpenAI LLM."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY is not configured")
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.8,
        max_output_tokens: int = 2000,
    ) -> str:
        """
        Generate content using OpenAI.

        Args:
            prompt: User prompt
            system_instruction: Optional system instruction
            temperature: Creativity level (0.0-2.0)
            max_output_tokens: Maximum tokens in response

        Returns:
            Generated text content
        """
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

        content = response.choices[0].message.content or ""
        logger.debug(f"Generated content with {len(content)} characters")
        return content


# Singleton instance for dependency injection
openai_client = OpenAIClient()
