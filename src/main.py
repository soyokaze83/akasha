"""Akasha - Multi-Service WhatsApp Platform.

FastAPI application entry point with lifespan management.
"""

import hmac
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

from src.core.config import settings
from src.core.logging import setup_logging
from src.core.scheduler import start_scheduler, shutdown_scheduler, scheduler
from src.core.gowa import gowa_client
from src.services.mandarin_generator import router as mandarin_router
from src.services.reply_agent import reply_agent

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)

# In-memory store for Akasha's sent message IDs
# Key: message_id, Value: timestamp (for cleanup)
akasha_message_ids: dict[str, float] = {}

# Cleanup threshold: 24 hours
MESSAGE_ID_TTL = 86400


def cleanup_old_message_ids() -> None:
    """Remove message IDs older than 24 hours."""
    cutoff = time.time() - MESSAGE_ID_TTL
    expired = [k for k, v in akasha_message_ids.items() if v < cutoff]
    for k in expired:
        del akasha_message_ids[k]
    if expired:
        logger.debug(f"Cleaned up {len(expired)} old message IDs")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown."""
    # Startup
    logger.info(f"Starting {settings.app_name}...")
    start_scheduler()
    yield
    # Shutdown
    logger.info("Shutting down...")
    shutdown_scheduler()


app = FastAPI(
    title="Akasha",
    description="Multi-Service WhatsApp Platform - Daily Mandarin passages and more",
    version="0.1.0",
    lifespan=lifespan,
)

# Include service routers
app.include_router(mandarin_router)


# Health check models
class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    gowa_connected: bool
    scheduler_running: bool


@app.get("/")
async def root() -> dict:
    """Root endpoint with service info."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "description": "Multi-Service WhatsApp Platform",
        "services": ["mandarin_generator", "reply_agent"],
    }


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health including GoWA connection and scheduler status."""
    gowa_healthy = await gowa_client.check_health()
    scheduler_running = scheduler.running

    status = "healthy" if (gowa_healthy and scheduler_running) else "degraded"

    return HealthResponse(
        status=status,
        gowa_connected=gowa_healthy,
        scheduler_running=scheduler_running,
    )


@app.post("/webhook")
async def handle_webhook(request: Request) -> dict:
    """
    Handle incoming WhatsApp webhook events from GoWA.

    Triggers Reply Agent for messages starting with "hey akasha, ".
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Verify signature if secret is configured
    if settings.gowa_webhook_secret and settings.gowa_webhook_secret != "your-secret-key":
        expected = "sha256=" + hmac.new(
            settings.gowa_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            logger.warning("Webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()

        sender = payload.get("pushname", "unknown")
        sender_jid = payload.get("from", "")
        message_data = payload.get("message", {})
        message_text = message_data.get("text", "")
        message_id = message_data.get("id", "")
        replied_id = message_data.get("replied_id", "")
        quoted_message = message_data.get("quoted_message", "")

        # Determine event type from payload structure
        if payload.get("reaction"):
            event_type = "reaction"
        elif message_text:
            event_type = "message.text"
        else:
            event_type = "other"

        logger.info(f"Webhook received: type={event_type}, from={sender} ({sender_jid})")

        # Debug: log reply-related fields
        if replied_id or quoted_message:
            logger.info(f"Reply context: replied_id={replied_id}, quoted_message={quoted_message[:50] if quoted_message else 'None'}...")
            logger.info(f"Tracked message IDs: {list(akasha_message_ids.keys())}")

        # Lazy cleanup of old message IDs
        cleanup_old_message_ids()

        # Handle Reply Agent triggers
        if settings.reply_agent_enabled and event_type == "message.text" and message_text:
            # Check if replying to Akasha's message (no prefix needed)
            is_reply_to_akasha = replied_id and replied_id in akasha_message_ids
            logger.debug(f"Reply check: replied_id={replied_id}, is_reply_to_akasha={is_reply_to_akasha}")

            # Determine if should trigger and extract query
            should_process = False
            query = ""
            quoted_context = quoted_message if quoted_message else None

            if reply_agent.should_trigger(message_text):
                # "hey akasha, ..." - extract query after trigger phrase
                query = reply_agent.extract_query(message_text)
                should_process = True
                logger.info(f"Reply Agent triggered by {sender}: {query}")
            elif is_reply_to_akasha:
                # Replying to Akasha without prefix - use full message as query
                query = message_text
                should_process = True
                logger.info(f"Reply Agent triggered by reply to Akasha from {sender}: {query}")

            if should_process:
                # Extract reply JID - handle group messages
                # Format for groups: "phone@s.whatsapp.net in groupid@g.us"
                reply_jid = sender_jid
                if " in " in sender_jid:
                    # Group message - reply to the group, not the individual
                    reply_jid = sender_jid.split(" in ")[1]

                try:
                    response_text, sources = await reply_agent.process_query(
                        query, quoted_context
                    )

                    result = await gowa_client.send_message(
                        phone=reply_jid,
                        message=response_text,
                        reply_message_id=message_id,
                    )

                    # Track Akasha's sent message ID for reply detection
                    # GoWA returns message_id at top level, not nested
                    sent_message_id = result.get("message_id")
                    if sent_message_id:
                        akasha_message_ids[sent_message_id] = time.time()
                        logger.info(f"Tracked message ID: {sent_message_id}")
                    else:
                        logger.warning(f"No message_id in GoWA response: {result}")

                    logger.info(f"Reply Agent response sent to {reply_jid}")

                except Exception as e:
                    logger.exception(f"Reply Agent error: {e}")

                    # Determine user-friendly error message based on error type
                    error_str = str(e).lower()
                    if "429" in str(e) or "quota" in error_str or "rate" in error_str:
                        error_message = (
                            "I'm currently experiencing high demand and hit my rate limit. "
                            "Please wait a moment and try again."
                        )
                    elif "exhausted" in error_str or "all api keys" in error_str:
                        error_message = (
                            "All my API resources are temporarily exhausted. "
                            "Please try again in a few minutes."
                        )
                    elif "timeout" in error_str:
                        error_message = (
                            "The request took too long to process. "
                            "Please try again with a simpler question."
                        )
                    elif "api" in error_str and "key" in error_str:
                        error_message = (
                            "I'm having trouble connecting to my AI service. "
                            "Please notify the administrator."
                        )
                    else:
                        error_message = (
                            "Sorry, I encountered an error processing your request. "
                            "Please try again."
                        )

                    error_result = await gowa_client.send_message(
                        phone=reply_jid,
                        message=error_message,
                        reply_message_id=message_id,
                    )
                    # Also track error message IDs so user can reply to them
                    sent_message_id = error_result.get("message_id")
                    if sent_message_id:
                        akasha_message_ids[sent_message_id] = time.time()

    except Exception as e:
        logger.error(f"Failed to process webhook: {e}")
        # Return 200 to prevent GoWA retries even on processing errors

    return {"status": "ok"}
