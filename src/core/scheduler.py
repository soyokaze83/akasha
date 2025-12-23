"""APScheduler integration for scheduled tasks."""

import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import settings

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.timezone))


def configure_scheduler() -> None:
    """Configure all scheduled jobs."""
    from src.services.mandarin_generator.tasks import send_daily_passage

    # Daily Mandarin passage job
    scheduler.add_job(
        send_daily_passage,
        trigger=CronTrigger(
            hour=settings.daily_passage_hour,
            minute=settings.daily_passage_minute,
            timezone=pytz.timezone(settings.timezone),
        ),
        id="daily_mandarin_passage",
        name="Daily Mandarin Passage",
        replace_existing=True,
    )

    logger.info(
        f"Scheduled daily Mandarin passage at "
        f"{settings.daily_passage_hour:02d}:{settings.daily_passage_minute:02d} "
        f"({settings.timezone})"
    )


def start_scheduler() -> None:
    """Start the scheduler."""
    configure_scheduler()
    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown")
