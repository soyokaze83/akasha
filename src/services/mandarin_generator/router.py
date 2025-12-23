"""FastAPI router for Mandarin Generator service."""

import logging
from datetime import datetime

from fastapi import APIRouter

from src.core.config import settings
from src.core.gowa import gowa_client
from src.core.gowa.client import GowaClientError
from src.services.mandarin_generator.models import (
    GeneratePassageRequest,
    GeneratePassageResponse,
    TriggerDailyResponse,
)
from src.services.mandarin_generator.service import passage_generator
from src.services.mandarin_generator.tasks import send_daily_passage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mandarin", tags=["mandarin"])


@router.post("/generate", response_model=GeneratePassageResponse)
async def generate_passage(request: GeneratePassageRequest) -> GeneratePassageResponse:
    """
    Generate and optionally send a Mandarin reading passage.

    - If recipient is provided, sends only to that recipient.
    - If recipient is not provided, sends to all configured recipients.
    - If no recipients configured and none provided, just returns the passage.
    """
    passage, topic = await passage_generator.generate_passage(topic=request.topic)

    # Determine recipients
    recipients: list[str] = []
    if request.recipient:
        recipients = [request.recipient]
    else:
        recipients = settings.recipients_list

    # Send to recipients if any
    sent_to: list[str] = []
    if recipients:
        today = datetime.now().strftime("%Y年%m月%d日")
        message = f"📚 中文阅读 - {today}\n\n{passage}"

        for recipient in recipients:
            try:
                await gowa_client.send_message(phone=recipient, message=message)
                sent_to.append(recipient)
                logger.info(f"Passage sent to {recipient}")
            except GowaClientError as e:
                logger.error(f"Failed to send to {recipient}: {e}")

    return GeneratePassageResponse(
        passage=passage,
        topic=topic,
        generated_at=datetime.now(),
        sent_to=sent_to,
    )


@router.post("/trigger-daily", response_model=TriggerDailyResponse)
async def trigger_daily() -> TriggerDailyResponse:
    """
    Manually trigger the daily passage job.

    Useful for testing or sending an extra passage outside the schedule.
    """
    await send_daily_passage()
    return TriggerDailyResponse(
        status="triggered",
        message="Daily passage job has been triggered",
    )
