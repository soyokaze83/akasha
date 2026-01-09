"""Akasha - Multi-Service WhatsApp Platform.

FastAPI application entry point with lifespan management.
"""

import asyncio
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
from src.core.rate_limiter import rate_limiter
from src.core.background_tasks import (
    process_text_reply_background,
    process_image_reply_background,
)
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

# In-memory set to track processed message IDs (prevent duplicate processing)
# Key: message_id, Value: timestamp
processed_message_ids: dict[str, float] = {}

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

    # Cleanup old processed message IDs
    expired_processed = [k for k, v in processed_message_ids.items() if v < cutoff]
    for k in expired_processed:
        del processed_message_ids[k]
    if expired_processed:
        logger.debug(f"Cleaned up {len(expired_processed)} old processed message IDs")


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
    if (
        settings.gowa_webhook_secret
        and settings.gowa_webhook_secret != "your-secret-key"
    ):
        expected = (
            "sha256="
            + hmac.new(
                settings.gowa_webhook_secret.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
        )

        if not hmac.compare_digest(signature, expected):
            logger.warning("Webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()

        sender = payload.get("pushname", "unknown")
        sender_jid = payload.get("from", "")

        # Rate limit check - prevent DoS attacks
        if sender_jid and not await rate_limiter.is_allowed(sender_jid):
            logger.warning(f"Rate limit exceeded for {sender_jid}")
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        message_data = payload.get("message", {})

        # Check for media messages (image/video/audio) - ID is at top level
        image_info = payload.get("image")
        video_info = payload.get("video")
        audio_info = payload.get("audio")
        is_media_message = any(
            [
                isinstance(image_info, dict),
                isinstance(video_info, dict),
                isinstance(audio_info, dict),
            ]
        )

        # Unified message ID extraction - try multiple locations for compatibility
        # GoWA docs say media messages have ID at top level, but we also check message object
        if is_media_message:
            message_text = ""
            replied_id = payload.get("replied_id", "")
            quoted_message = payload.get("quoted_message", "")
            has_image = isinstance(image_info, dict)

            # Try top-level ID first (for media messages), then fallback to message object
            message_id = payload.get("id", "") or payload.get("message", {}).get(
                "id", ""
            )

            # Log which location we found the ID in
            if payload.get("id"):
                logger.info(f"Found message_id at top level for media message")
            elif payload.get("message", {}).get("id"):
                logger.info(f"Found message_id in message object for media message")
            else:
                logger.warning(
                    f"No message_id found in either top level or message object. "
                    f"Payload keys: {list(payload.keys())}, "
                    f"message keys: {list(payload.get('message', {}).keys())}"
                )
        else:
            message_text = message_data.get("text", "")
            message_id = message_data.get("id", "")
            replied_id = message_data.get("replied_id", "")
            quoted_message = message_data.get("quoted_message", "")
            has_image = False

        # Determine event type from payload structure
        if payload.get("reaction"):
            event_type = "reaction"
        elif has_image:
            event_type = "message.image"
        elif message_text:
            event_type = "message.text"
        else:
            event_type = "other"

        logger.info(
            f"Webhook received: type={event_type}, from={sender} ({sender_jid})"
        )

        # Skip if this is Akasha's own message (prevent self-replies)
        if message_id and message_id in akasha_message_ids:
            logger.debug(f"Skipping own message: {message_id}")
            return {"status": "ok"}

        # Skip if we've already processed this message (prevent duplicate processing)
        if message_id and message_id in processed_message_ids:
            logger.debug(f"Skipping already processed message: {message_id}")
            return {"status": "ok"}

        # Mark message as being processed IMMEDIATELY to prevent duplicate processing on timeout
        if message_id:
            processed_message_ids[message_id] = time.time()
            logger.debug(f"Marked message {message_id} as processed")

        # Debug: log payload structure (not content to avoid PII)
        logger.debug(f"Webhook payload keys: {list(payload.keys())}")

        # Cache file_path for any incoming media (for later reply-to-image lookups)
        file_path = payload.get("file_path")
        media_message_id = payload.get("id")
        if file_path and media_message_id:
            media_file_paths[media_message_id] = (file_path, time.time())
            logger.info(
                f"Cached media file path for message {media_message_id}: {file_path}"
            )

        # Debug: log reply context (truncated to avoid PII)
        if replied_id or quoted_message:
            logger.debug(
                f"Reply context: replied_id={replied_id}, "
                f"has_quoted_message={bool(quoted_message)}"
            )

        # Lazy cleanup of old message IDs
        cleanup_old_message_ids()

        # Handle Reply Agent triggers for text messages
        if (
            settings.reply_agent_enabled
            and event_type == "message.text"
            and message_text
        ):
            # Check if replying to Akasha's message (no prefix needed)
            is_reply_to_akasha = replied_id and replied_id in akasha_message_ids
            logger.debug(
                f"Reply check: replied_id={replied_id}, is_reply_to_akasha={is_reply_to_akasha}"
            )

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
                logger.info(
                    f"Reply Agent triggered by reply to Akasha from {sender}: {query}"
                )

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
                    # Use 'from' field for phone (not 'chat_id' which may be a LID)
                    # Format: "6289608842518:40@s.whatsapp.net in 6289608842518@s.whatsapp.net"
                    # We need "6289608842518@s.whatsapp.net" (the chat JID, not the device JID)
                    from_jid = payload.get("from") or sender_jid
                    # For "X in Y" format, use Y (the chat JID)
                    if " in " in from_jid:
                        phone_for_download = from_jid.split(" in ")[1]
                    else:
                        # Strip device ID if present (e.g., "6289608842518:40@s.whatsapp.net" -> "6289608842518@s.whatsapp.net")
                        phone_for_download = (
                            from_jid.split(":")[0] + "@s.whatsapp.net"
                            if ":" in from_jid and "@" in from_jid
                            else from_jid
                        )

                    # GoWA may include file_path for quoted media directly in the webhook
                    quoted_file_path = payload.get("file_path")
                    if quoted_file_path:
                        logger.info(
                            f"Found file_path in webhook for quoted message: {quoted_file_path}"
                        )
                        try:
                            (
                                quoted_image_data,
                                quoted_image_mime,
                            ) = await gowa_client.download_media_from_path(
                                quoted_file_path
                            )
                            logger.info(
                                f"Downloaded quoted image from webhook file_path: {quoted_image_mime}, {len(quoted_image_data)} bytes"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to download from webhook file_path {quoted_file_path}: {e}"
                            )

                    # Try cached file path (from previous image webhooks)
                    if not quoted_image_data and replied_id in media_file_paths:
                        cached_path, _ = media_file_paths[replied_id]
                        try:
                            (
                                quoted_image_data,
                                quoted_image_mime,
                            ) = await gowa_client.download_media_from_path(cached_path)
                            logger.info(
                                f"Downloaded quoted image from cached path: {quoted_image_mime}, {len(quoted_image_data)} bytes"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to download from cached path {cached_path}: {e}"
                            )

                    # Fallback: try on-demand download API (when auto-download is disabled)
                    if not quoted_image_data:
                        # Ensure phone has the right format (with @s.whatsapp.net suffix)
                        if not phone_for_download.endswith("@s.whatsapp.net"):
                            phone_for_download = f"{phone_for_download}@s.whatsapp.net"
                        logger.info(
                            f"Attempting download API with message_id={replied_id}, phone={phone_for_download}"
                        )
                        try:
                            (
                                quoted_image_data,
                                quoted_image_mime,
                            ) = await gowa_client.download_media(
                                message_id=replied_id,
                                phone=phone_for_download,
                            )
                            logger.info(
                                f"Downloaded quoted image via API: {quoted_image_mime}, {len(quoted_image_data)} bytes"
                            )
                        except Exception as e:
                            # Log the actual error to understand why download failed
                            logger.warning(
                                f"Failed to download media for quoted message {replied_id}: {e}"
                            )

                # Process in background to avoid blocking webhook handler
                # This allows GoWA to receive 200 OK within timeout while LLM processes
                asyncio.create_task(
                    process_text_reply_background(
                        reply_agent=reply_agent,
                        query=query,
                        reply_jid=reply_jid,
                        message_id=message_id,
                        quoted_context=quoted_context,
                        image_data=quoted_image_data,
                        image_mime_type=quoted_image_mime,
                        akasha_message_ids=akasha_message_ids,
                    )
                )
                logger.info(f"Text reply queued for background processing: {query[:50]}...")

        # Handle Reply Agent triggers for image messages
        elif (
            settings.reply_agent_enabled
            and event_type == "message.image"
            and image_info
        ):
            # Get image caption and message ID for download
            image_caption = image_info.get("caption", "")
            payload_id = message_id
            # Use 'from' field for phone (not 'chat_id' which may be a LID)
            from_jid = payload.get("from") or sender_jid

            # Check if replying to Akasha's message
            is_reply_to_akasha = replied_id and replied_id in akasha_message_ids

            # Determine if should trigger and extract query
            should_process = False
            query = ""

            if image_caption.lower().startswith(reply_agent.TRIGGER_PHRASE):
                # "hey akasha, ..." in caption - extract query
                query = image_caption[len(reply_agent.TRIGGER_PHRASE) :].strip()
                should_process = True
                logger.info(
                    f"Reply Agent (image) triggered by {sender}: query='{query}', "
                    f"message_id={payload_id}, from_jid={from_jid}, "
                    f"caption={image_caption[:100] if image_caption else '(empty)'}"
                )
            elif is_reply_to_akasha:
                # Replying to Akasha with an image - use caption or default prompt
                query = image_caption.strip() if image_caption else ""
                should_process = True
                logger.info(
                    f"Reply Agent (image) triggered by reply to Akasha from {sender}"
                )

            if should_process and payload_id:
                # Extract reply JID - handle group messages
                reply_jid = sender_jid
                if " in " in sender_jid:
                    reply_jid = sender_jid.split(" in ")[1]

                # Download image first (must complete before background processing)
                # Try cached file path first, then on-demand API
                image_bytes = None
                mime_type = None
                download_error = None

                try:
                    # Try cached file path first (when GoWA auto-downloads)
                    if payload_id in media_file_paths:
                        cached_path, _ = media_file_paths[payload_id]
                        try:
                            (
                                image_bytes,
                                mime_type,
                            ) = await gowa_client.download_media_from_path(cached_path)
                            logger.info(
                                f"Downloaded image from cached path: {mime_type}, {len(image_bytes)} bytes"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to download from cached path {cached_path}: {e}"
                            )

                    # Fallback: try on-demand download API
                    if not image_bytes:
                        # Normalize phone parameter for download API
                        if " in " in from_jid:
                            phone_for_download = from_jid.split(" in ")[1]
                        else:
                            # Strip device ID if present
                            phone_for_download = (
                                from_jid.split(":")[0] + "@s.whatsapp.net"
                                if ":" in from_jid and "@" in from_jid
                                else from_jid
                            )

                        # Ensure phone has proper @s.whatsapp.net suffix
                        if not phone_for_download.endswith("@s.whatsapp.net"):
                            phone_for_download = f"{phone_for_download}@s.whatsapp.net"

                        logger.info(
                            f"Attempting image download via API: message_id={payload_id}, phone={phone_for_download}"
                        )
                        image_bytes, mime_type = await gowa_client.download_media(
                            message_id=payload_id,
                            phone=phone_for_download,
                        )
                        logger.info(
                            f"Image downloaded successfully: {mime_type}, {len(image_bytes)} bytes"
                        )
                except Exception as e:
                    download_error = e
                    logger.exception(f"Failed to download image: {e}")

                if download_error or not image_bytes:
                    # Send error message for download failure
                    error_message = (
                        "I couldn't download the image. "
                        "Please try sending it again."
                    )
                    try:
                        error_result = await gowa_client.send_message(
                            phone=reply_jid,
                            message=error_message,
                            reply_message_id=payload_id,
                        )
                        sent_message_id = error_result.get("message_id")
                        if sent_message_id:
                            akasha_message_ids[sent_message_id] = time.time()
                    except Exception as send_error:
                        logger.error(f"Failed to send download error message: {send_error}")
                else:
                    # Use caption as query, or default to asking about the image
                    if not query:
                        query = "What is in this image?"

                    # Get quoted context for image replies
                    quoted_context = quoted_message if quoted_message else None

                    # Process in background to avoid blocking webhook handler
                    asyncio.create_task(
                        process_image_reply_background(
                            reply_agent=reply_agent,
                            query=query,
                            reply_jid=reply_jid,
                            message_id=payload_id,
                            image_data=image_bytes,
                            image_mime_type=mime_type,
                            quoted_context=quoted_context,
                            akasha_message_ids=akasha_message_ids,
                        )
                    )
                    logger.info(f"Image reply queued for background processing: {query[:50]}...")
            else:
                # Log why we're skipping processing
                if should_process and not payload_id:
                    logger.warning(
                        f"Skipping image processing - no message_id available. "
                        f"trigger_detected=True, message_id='{payload_id}', "
                        f"payload id field='{payload.get('id', 'MISSING')}', "
                        f"message.id='{payload.get('message', {}).get('id', 'MISSING')}'"
                    )

    except Exception as e:
        logger.error(f"Failed to process webhook: {e}")
        # Return 200 to prevent GoWA retries even on processing errors

    return {"status": "ok"}
