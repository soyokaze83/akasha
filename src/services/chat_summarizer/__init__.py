"""Chat summarizer service module."""

from src.services.chat_summarizer.router import router
from src.services.chat_summarizer.service import chat_summarizer

__all__ = ["router", "chat_summarizer"]
