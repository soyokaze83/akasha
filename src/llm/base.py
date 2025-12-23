"""Unified LLM interface for provider switching."""

import logging
from typing import Optional, Protocol

from src.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM clients."""

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.8,
        max_output_tokens: int = 2000,
    ) -> str:
        """Generate content from the LLM."""
        ...


def get_llm_client() -> LLMClient:
    """
    Get the configured LLM client based on LLM_PROVIDER setting.

    Returns:
        LLMClient instance (either Gemini or OpenAI)

    Raises:
        ValueError: If provider is not supported or not configured
    """
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        from src.llm.gemini import gemini_client

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        logger.info(f"Using Gemini LLM provider (model: {settings.gemini_model})")
        return gemini_client

    elif provider == "openai":
        from src.llm.openai import openai_client

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        logger.info(f"Using OpenAI LLM provider (model: {settings.openai_model})")
        return openai_client

    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: {provider}. Supported: gemini, openai"
        )


# Lazy-loaded singleton
_llm_client: Optional[LLMClient] = None


def get_configured_llm() -> LLMClient:
    """Get the singleton LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = get_llm_client()
    return _llm_client
