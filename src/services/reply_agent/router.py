"""FastAPI router for Reply Agent service."""

import logging

from fastapi import APIRouter

from src.core.config import settings
from src.core.gowa import gowa_client
from src.core.gowa.client import GowaClientError
from src.services.reply_agent.models import QueryRequest, QueryResponse
from src.services.reply_agent.service import reply_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reply-agent", tags=["reply-agent"])


@router.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest) -> QueryResponse:
    """
    Process a query using the Reply Agent.

    - Uses the configured LLM provider (Gemini or OpenAI) with automatic fallback
    - Can optionally include quoted context for reply-aware responses
    - If recipient is provided, sends the response via WhatsApp
    - Returns the response and any sources used from web search
    """
    # Process the query
    response_text, sources = await reply_agent.process_query(
        query=request.query,
        quoted_context=request.quoted_context,
    )

    # Determine which provider was used (for debugging/info)
    provider_used = settings.llm_provider

    # Send to recipient if provided
    sent_to = None
    if request.recipient:
        try:
            await gowa_client.send_message(
                phone=request.recipient,
                message=response_text,
            )
            sent_to = request.recipient
            logger.info(f"Reply Agent response sent to {request.recipient}")
        except GowaClientError as e:
            logger.error(f"Failed to send to {request.recipient}: {e}")

    return QueryResponse(
        response=response_text,
        sources_used=sources,
        sent_to=sent_to,
        provider_used=provider_used,
    )


@router.get("/status")
async def get_status() -> dict:
    """
    Get the current status of the Reply Agent.

    Returns configuration info about the agent.
    """
    return {
        "enabled": settings.reply_agent_enabled,
        "primary_provider": settings.llm_provider,
        "fallback_enabled": settings.llm_fallback_enabled,
        "trigger_phrase": reply_agent.TRIGGER_PHRASE,
        "gemini_configured": bool(settings.gemini_api_key),
        "openai_configured": bool(settings.openai_api_key),
        "web_search_configured": bool(
            settings.google_search_api_key and settings.google_search_engine_id
        ),
    }
