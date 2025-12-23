"""Scheduled tasks for Mandarin Generator service."""

import logging
from datetime import date

from src.core.config import settings
from src.core.gowa import gowa_client
from src.core.gowa.client import GowaClientError
from src.services.mandarin_generator.service import passage_generator

logger = logging.getLogger(__name__)


async def send_daily_passage() -> None:
    """
    Generate and send daily Mandarin passage to all recipients.

    This function is called by the scheduler at the configured time.
    """
    logger.info("Starting daily Mandarin passage generation...")

    recipients = settings.recipients_list
    if not recipients:
        logger.warning("No recipients configured, skipping daily passage")
        return

    try:
        # Generate the passage
        passage, topic = await passage_generator.generate_passage()

        # Format the message with date header
        today = date.today().strftime("%Y年%m月%d日")
        message = f"📚 每日中文阅读 - {today}\n\n{passage}"

        # Send to all recipients
        success_count = 0
        for recipient in recipients:
            try:
                await gowa_client.send_message(phone=recipient, message=message)
                success_count += 1
                logger.info(f"Daily passage sent to {recipient}")
            except GowaClientError as e:
                logger.error(f"Failed to send to {recipient}: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error sending to {recipient}: {e}")

        logger.info(
            f"Daily passage completed: {success_count}/{len(recipients)} recipients "
            f"(topic: {topic})"
        )

    except Exception as e:
        logger.exception(f"Failed to generate daily passage: {e}")
