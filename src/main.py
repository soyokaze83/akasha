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
from src.services.reply_agent import reply_agent, router as reply_agent_router

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)

# In-memory store for Akasha's sent message IDs
# Key: message_id, Value: timestamp (for cleanup)
akasha_message_ids: dict[str, float] = {}

# In-memory cache for media file paths from auto-downloaded images
# Key: message_id, Value: (file_path, timestamp)
media_file_paths: dict[str, tuple[str, float]] = {}

# Cleanup threshold: 24 hours
MESSAGE_ID_TTL = 86400


def cleanup_old_message_ids() -> None:
    """Remove message IDs and media paths older than 24 hours."""
    cutoff = time.time() - MESSAGE_ID_TTL
    expired = [k for k, v in akasha_message_ids.items() if v < cutoff]
    for k in expired:
        del akasha_message_ids[k]
    if expired:
        logger.debug(f"Cleaned up {len(expired)} old message IDs")

    # Also cleanup old media file paths
    expired_media = [k for k, v in media_file_paths.items() if v[1] < cutoff]
    for k in expired_media:
        del media_file_paths[k]
    if expired_media:
        logger.debug(f"Cleaned up {len(expired_media)} old media file paths")


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
app.include_router(reply_agent_router)


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

        # Check for image message (with auto-download disabled, image is an object)
        image_info = payload.get("image")
        has_image = isinstance(image_info, dict)

        # Determine event type from payload structure
        if payload.get("reaction"):
            event_type = "reaction"
        elif has_image:
            event_type = "message.image"
        elif message_text:
            event_type = "message.text"
        else:
            event_type = "other"

        logger.info(f"Webhook received: type={event_type}, from={sender} ({sender_jid})")

        # Cache file_path for any incoming media (for later reply-to-image lookups)
        file_path = payload.get("file_path")
        media_message_id = payload.get("id")
        if file_path and media_message_id:
            media_file_paths[media_message_id] = (file_path, time.time())
            logger.info(f"Cached media file path for message {media_message_id}: {file_path}")

        # Debug: log reply-related fields
        if replied_id or quoted_message:
            logger.info(f"Reply context: replied_id={replied_id}, quoted_message={quoted_message[:50] if quoted_message else 'None'}...")
            logger.info(f"Tracked message IDs: {list(akasha_message_ids.keys())}")

        # Lazy cleanup of old message IDs
        cleanup_old_message_ids()

        # Handle Reply Agent triggers for text messages
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

                # Check if user is replying to an image message (try to download quoted media)
                quoted_image_data = None
                quoted_image_mime = None
                if replied_id:
                    chat_id = payload.get("chat_id") or sender_jid
                    phone_for_download = chat_id.split(" in ")[0] if " in " in chat_id else chat_id

                    # First, try to get from cached file path (when GoWA auto-downloads)
                    if replied_id in media_file_paths:
                        cached_path, _ = media_file_paths[replied_id]
                        try:
                            quoted_image_data, quoted_image_mime = await gowa_client.download_media_from_path(cached_path)
                            logger.info(f"Downloaded quoted image from cached path: {quoted_image_mime}, {len(quoted_image_data)} bytes")
                        except Exception as e:
                            logger.warning(f"Failed to download from cached path {cached_path}: {e}")

                    # Fallback: try on-demand download API (when auto-download is disabled)
                    if not quoted_image_data:
                        try:
                            quoted_image_data, quoted_image_mime = await gowa_client.download_media(
                                message_id=replied_id,
                                phone=phone_for_download,
                            )
                            logger.info(f"Downloaded quoted image via API: {quoted_image_mime}, {len(quoted_image_data)} bytes")
                        except Exception as e:
                            # Not an image or download failed - that's fine, continue without image
                            logger.debug(f"No downloadable media in quoted message {replied_id}: {e}")

                try:
                    response_text, sources = await reply_agent.process_query(
                        query=query,
                        quoted_context=quoted_context,
                        image_data=quoted_image_data,
                        image_mime_type=quoted_image_mime,
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

        # Handle Reply Agent triggers for image messages
        elif settings.reply_agent_enabled and event_type == "message.image" and image_info:
            # Get image caption and message ID for download
            image_caption = image_info.get("caption", "")
            payload_id = payload.get("id", "")
            chat_id = payload.get("chat_id") or sender_jid

            # Check if replying to Akasha's message
            is_reply_to_akasha = replied_id and replied_id in akasha_message_ids

            # Determine if should trigger and extract query
            should_process = False
            query = ""

            if image_caption.lower().startswith(reply_agent.TRIGGER_PHRASE):
                # "hey akasha, ..." in caption - extract query
                query = image_caption[len(reply_agent.TRIGGER_PHRASE):].strip()
                should_process = True
                logger.info(f"Reply Agent (image) triggered by {sender}: {query}")
            elif is_reply_to_akasha:
                # Replying to Akasha with an image - use caption or default prompt
                query = image_caption.strip() if image_caption else ""
                should_process = True
                logger.info(f"Reply Agent (image) triggered by reply to Akasha from {sender}")

            if should_process and payload_id:
                # Extract reply JID - handle group messages
                reply_jid = sender_jid
                if " in " in sender_jid:
                    reply_jid = sender_jid.split(" in ")[1]

                try:
                    # Try to download image - first from cached file path, then via API
                    image_bytes = None
                    mime_type = None

                    # Try cached file path first (when GoWA auto-downloads)
                    if payload_id in media_file_paths:
                        cached_path, _ = media_file_paths[payload_id]
                        try:
                            image_bytes, mime_type = await gowa_client.download_media_from_path(cached_path)
                            logger.info(f"Downloaded image from cached path: {mime_type}, {len(image_bytes)} bytes")
                        except Exception as e:
                            logger.warning(f"Failed to download from cached path {cached_path}: {e}")

                    # Fallback: try on-demand download API
                    if not image_bytes:
                        image_bytes, mime_type = await gowa_client.download_media(
                            message_id=payload_id,
                            phone=chat_id.split(" in ")[0] if " in " in chat_id else chat_id,
                        )

                    # Use caption as query, or default to asking about the image
                    if not query:
                        query = "What is in this image?"

                    response_text, sources = await reply_agent.process_query(
                        query=query,
                        image_data=image_bytes,
                        image_mime_type=mime_type,
                    )

                    result = await gowa_client.send_message(
                        phone=reply_jid,
                        message=response_text,
                        reply_message_id=payload_id,
                    )

                    # Track Akasha's sent message ID
                    sent_message_id = result.get("message_id")
                    if sent_message_id:
                        akasha_message_ids[sent_message_id] = time.time()
                        logger.info(f"Tracked message ID: {sent_message_id}")

                    logger.info(f"Reply Agent (image) response sent to {reply_jid}")

                except Exception as e:
                    logger.exception(f"Reply Agent (image) error: {e}")

                    # User-friendly error message
                    error_str = str(e).lower()
                    if "download" in error_str or "media" in error_str:
                        error_message = (
                            "I couldn't download the image. "
                            "Please try sending it again."
                        )
                    elif "429" in str(e) or "quota" in error_str or "rate" in error_str:
                        error_message = (
                            "I'm currently experiencing high demand. "
                            "Please wait a moment and try again."
                        )
                    elif "exhausted" in error_str or "all api keys" in error_str:
                        error_message = (
                            "All my API resources are temporarily exhausted. "
                            "Please try again in a few minutes."
                        )
                    else:
                        error_message = (
                            "Sorry, I couldn't process the image. "
                            "Please try again."
                        )

                    error_result = await gowa_client.send_message(
                        phone=reply_jid,
                        message=error_message,
                        reply_message_id=payload_id,
                    )
                    sent_message_id = error_result.get("message_id")
                    if sent_message_id:
                        akasha_message_ids[sent_message_id] = time.time()

    except Exception as e:
        logger.error(f"Failed to process webhook: {e}")
        # Return 200 to prevent GoWA retries even on processing errors

    return {"status": "ok"}
