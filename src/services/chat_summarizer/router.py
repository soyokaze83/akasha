"""FastAPI router for chat summarizer endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter

from src.core.config import settings
from src.core.gowa import gowa_client
from src.services.chat_summarizer.models import SummarizeRequest, SummarizeResponse
from src.services.chat_summarizer.service import chat_summarizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat-summarizer", tags=["chat-summarizer"])


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_chat(request: SummarizeRequest) -> SummarizeResponse:
    """Summarize messages from a chat."""
    # Enforce max limit
    message_count = min(request.message_count, settings.chat_summarizer_max_messages)

    # Fetch messages from GoWA
    messages = await gowa_client.get_chat_messages(
        chat_jid=request.chat_jid,
        limit=message_count,
    )

    # Generate summary
    summary, participants = await chat_summarizer.summarize_messages(messages)

    return SummarizeResponse(
        summary=summary,
        messages_analyzed=len(messages),
        participants=participants,
        generated_at=datetime.now(),
    )


@router.get("/status")
async def get_status() -> dict:
    """Get chat summarizer status."""
    return {
        "enabled": settings.chat_summarizer_enabled,
        "max_messages": settings.chat_summarizer_max_messages,
    }
