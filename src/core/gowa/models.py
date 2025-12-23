"""Pydantic models for GoWA webhook payloads and responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WebhookMessage(BaseModel):
    """Message content from webhook payload."""

    text: str = ""
    id: str = Field(default="", alias="id")
    replied_id: Optional[str] = ""
    quoted_message: Optional[str] = ""


class WebhookPayload(BaseModel):
    """GoWA webhook payload for incoming messages."""

    sender_id: str = ""
    chat_id: str = ""
    from_jid: str = Field(default="", alias="from")
    timestamp: Optional[datetime] = None
    pushname: str = ""
    type: str = ""
    message: Optional[WebhookMessage] = None

    model_config = {"populate_by_name": True}


class SendMessageRequest(BaseModel):
    """Request model for sending a message via GoWA."""

    phone: str
    message: str
    reply_message_id: Optional[str] = None


class SendMessageResult(BaseModel):
    """Result from GoWA send message endpoint."""

    message_id: str
    status: str


class GowaResponse(BaseModel):
    """Standard GoWA API response structure."""

    code: str
    message: str
    results: Optional[dict] = None
