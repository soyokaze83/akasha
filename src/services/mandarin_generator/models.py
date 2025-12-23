"""Pydantic models for Mandarin Generator service."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class GeneratePassageRequest(BaseModel):
    """Request model for manual passage generation."""

    topic: Optional[str] = None
    recipient: Optional[str] = None  # If None, sends to all configured recipients


class GeneratePassageResponse(BaseModel):
    """Response model for passage generation."""

    passage: str
    topic: str
    generated_at: datetime
    sent_to: list[str] = []


class TriggerDailyResponse(BaseModel):
    """Response model for triggering daily job."""

    status: str
    message: str
