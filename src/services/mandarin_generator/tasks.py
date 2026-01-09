"""Scheduled tasks for Mandarin Generator service."""

import asyncio
import logging
from datetime import date

from src.core.config import settings
from src.core.gowa import gowa_client
from src.core.gowa.client import GowaClientError
from src.services.mandarin_generator.service import (
    format_passage_message,
    passage_generator,
)

logger = logging.getLogger(__name__)

# In-memory tracking for idempotency (prevents duplicate sends on retry)
# Key: idempotency_key (e.g., "daily_passage_2026-01-09"), Value: set of sent recipients
sent_recipients: dict[str, set[str]] = {}


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


async def send_daily_passage() -> None:
    """
    Generate and send daily Mandarin passage to all recipients.

    This function is called by the scheduler at the configured time.
    Uses parallel sending with concurrency control and idempotency tracking.
    """
    logger.info("Starting daily Mandarin passage generation...")

    recipients = settings.recipients_list
    if not recipients:
        logger.warning("No recipients configured, skipping daily passage")
        return

    # Generate idempotency key for today
    idempotency_key = f"daily_passage_{date.today().isoformat()}"

    # Get already-sent recipients (for retry scenarios)
    already_sent = sent_recipients.get(idempotency_key, set())
    pending_recipients = [r for r in recipients if r not in already_sent]

    if not pending_recipients:
        logger.info(f"All recipients already received today's passage (key: {idempotency_key})")
        return

    if already_sent:
        logger.info(
            f"Resuming send: {len(already_sent)} already sent, "
            f"{len(pending_recipients)} pending"
        )

    try:
        # Generate the passage
        passage, topic = await passage_generator.generate_passage()

        # Format the message with standard header
        message = format_passage_message(passage)

        # Send to all pending recipients in parallel with concurrency limit
        semaphore = asyncio.Semaphore(settings.max_concurrent_sends)
        results = await asyncio.gather(
            *[_send_to_recipient(r, message, semaphore) for r in pending_recipients],
            return_exceptions=True,
        )

        # Process results and track successful sends
        success_count = len(already_sent)  # Start with already sent count
        failed_recipients = []

        for result in results:
            if isinstance(result, Exception):
                logger.exception(f"Unexpected error in parallel send: {result}")
                continue

            recipient, success, error_msg = result
            if success:
                success_count += 1
                # Track for idempotency
                if idempotency_key not in sent_recipients:
                    sent_recipients[idempotency_key] = set()
                sent_recipients[idempotency_key].add(recipient)
                logger.info(f"Daily passage sent to {recipient}")
            else:
                failed_recipients.append((recipient, error_msg))
                logger.error(f"Failed to send to {recipient}: {error_msg}")

        logger.info(
            f"Daily passage completed: {success_count}/{len(recipients)} recipients "
            f"(topic: {topic})"
        )

        if failed_recipients:
            logger.warning(
                f"Failed recipients: {[r for r, _ in failed_recipients]}"
            )

    except Exception as e:
        logger.exception(f"Failed to generate daily passage: {e}")


def cleanup_sent_recipients(days_to_keep: int = 7) -> int:
    """
    Clean up old idempotency tracking entries.

    Args:
        days_to_keep: Number of days of history to keep

    Returns:
        Number of entries cleaned up
    """
    from datetime import timedelta

    cutoff_date = date.today() - timedelta(days=days_to_keep)
    cutoff_key = f"daily_passage_{cutoff_date.isoformat()}"

    old_keys = [k for k in sent_recipients.keys() if k < cutoff_key]
    for key in old_keys:
        del sent_recipients[key]

    if old_keys:
        logger.debug(f"Cleaned up {len(old_keys)} old idempotency entries")

    return len(old_keys)
