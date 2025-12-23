"""Akasha - Multi-Service WhatsApp Platform.

FastAPI application entry point with lifespan management.
"""

import hmac
import hashlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

from src.core.config import settings
from src.core.logging import setup_logging
from src.core.scheduler import start_scheduler, shutdown_scheduler, scheduler
from src.core.gowa import gowa_client
from src.services.mandarin_generator import router as mandarin_router

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)


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
        "services": ["mandarin_generator"],
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

    Currently logs events for debugging. Can be extended for bot functionality.
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
        event_type = payload.get("type", "unknown")
        sender = payload.get("pushname", "unknown")
        sender_id = payload.get("sender_id", "unknown")

        logger.info(f"Webhook received: type={event_type}, from={sender} ({sender_id})")

        # Future: Add bot command handling here
        # Example:
        # if event_type == "message.text":
        #     message = payload.get("message", {}).get("text", "")
        #     if message.startswith("/passage"):
        #         await send_passage_to_sender(payload["from"])

    except Exception as e:
        logger.error(f"Failed to process webhook: {e}")
        # Return 200 to prevent GoWA retries even on processing errors

    return {"status": "ok"}
