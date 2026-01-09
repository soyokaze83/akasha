"""Pydantic models for chat summarizer service."""

from datetime import datetime

from pydantic import BaseModel


class SummarizeRequest(BaseModel):
    """Request model for chat summarization."""

    chat_jid: str
    message_count: int


class SummarizeResponse(BaseModel):
    """Response model for chat summarization."""

    summary: str
    messages_analyzed: int
    participants: list[str]
    generated_at: datetime
