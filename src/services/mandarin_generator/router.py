"""FastAPI router for Mandarin Generator service."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter  # noqa: F401

from src.core.config import settings
from src.core.gowa import gowa_client
from src.core.gowa.client import GowaClientError
from src.services.mandarin_generator.models import (
    GeneratePassageRequest,
    GeneratePassageResponse,
    TriggerDailyResponse,
)
from src.services.mandarin_generator.service import (
    format_passage_message,
    passage_generator,
)
from src.services.mandarin_generator.tasks import send_daily_passage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mandarin", tags=["mandarin"])


async def _send_to_recipient(
    recipient: str,
    message: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, bool, str]:
    """
    Send message to a single recipient with concurrency control.

    Args:
        recipient: The recipient JID
        message: The message to send
        semaphore: Semaphore for concurrency limiting

    Returns:
        Tuple of (recipient, success, error_message)
    """
    async with semaphore:
        try:
            await gowa_client.send_message(phone=recipient, message=message)
            return (recipient, True, "")
        except GowaClientError as e:
            return (recipient, False, str(e))
        except Exception as e:
            return (recipient, False, f"Unexpected: {e}")


@router.post("/generate", response_model=GeneratePassageResponse)
async def generate_passage(request: GeneratePassageRequest) -> GeneratePassageResponse:
    """
    Generate and optionally send a Mandarin reading passage.

    - If recipient is provided, sends only to that recipient.
    - If recipient is not provided, sends to all configured recipients.
    - If no recipients configured and none provided, just returns the passage.

    Uses parallel sending with concurrency control for multiple recipients.
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
        message = format_passage_message(passage)

        # Send in parallel with concurrency control
        semaphore = asyncio.Semaphore(settings.max_concurrent_sends)
        results = await asyncio.gather(
            *[_send_to_recipient(r, message, semaphore) for r in recipients],
            return_exceptions=True,
        )

        # Process results
        for result in results:
            if isinstance(result, Exception):
                logger.exception(f"Unexpected error in parallel send: {result}")
                continue

            recipient, success, error_msg = result
            if success:
                sent_to.append(recipient)
                logger.info(f"Passage sent to {recipient}")
            else:
                logger.error(f"Failed to send to {recipient}: {error_msg}")

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
