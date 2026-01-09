"""APScheduler integration for scheduled tasks."""

import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.core.config import settings

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler(timezone=pytz.timezone(settings.timezone))


async def _cleanup_caches() -> None:
    """Periodic cleanup of in-memory caches."""
    from src.core.rate_limiter import rate_limiter

    # Import cleanup function from main to avoid circular imports
    # We use a delayed import here
    try:
        from src.main import cleanup_old_message_ids

        cleanup_old_message_ids()
    except ImportError:
        logger.warning("Could not import cleanup_old_message_ids from main")

    # Cleanup rate limiter stale entries
    cleaned = await rate_limiter.cleanup()
    if cleaned:
        logger.debug(f"Cleaned up {cleaned} stale rate limiter entries")


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

    # Periodic cache cleanup job (every 30 minutes)
    scheduler.add_job(
        _cleanup_caches,
        trigger=IntervalTrigger(minutes=30),
        id="cache_cleanup",
        name="Cache Cleanup",
        replace_existing=True,
    )
    logger.info("Scheduled cache cleanup every 30 minutes")


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
