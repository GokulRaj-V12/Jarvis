"""
Scheduler Service — APScheduler for morning plans and evening reviews.
Modified for Discord.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import config
from services import memory_service, discord_service, personality_service

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def morning_routine():
    """Send morning plan to all users via Discord."""
    logger.info("Running morning routine...")
    user_ids = memory_service.get_all_user_ids()
    for uid in user_ids:
        try:
            plan = await discord_service.generate_plan_internal(uid)
            await discord_service.send_proactive_message(uid, f"☀️ **Good Morning!**\n\n{plan}")
        except Exception as e:
            logger.error(f"Morning routine failed for user {uid}: {e}")


async def evening_routine():
    """Send evening review to all users via Discord."""
    logger.info("Running evening routine...")
    user_ids = memory_service.get_all_user_ids()
    for uid in user_ids:
        try:
            review = await discord_service.generate_review_internal(uid)
            await discord_service.send_proactive_message(uid, f"🌙 **Evening Check-in**\n\n{review}")
        except Exception as e:
            logger.error(f"Evening routine failed for user {uid}: {e}")


async def weekly_personality_update():
    """Update personality profiles weekly for all users."""
    logger.info("Running weekly personality update...")
    user_ids = memory_service.get_all_user_ids()
    for uid in user_ids:
        try:
            await personality_service.update_personality(uid)
            logger.info(f"Updated personality for user {uid}")
        except Exception as e:
            logger.error(f"Personality update failed for user {uid}: {e}")


def start_scheduler():
    """Start the APScheduler with morning, evening, and weekly jobs."""
    # Morning plan
    scheduler.add_job(
        morning_routine,
        CronTrigger(
            hour=config.MORNING_HOUR,
            minute=config.MORNING_MINUTE,
            timezone=config.USER_TIMEZONE,
        ),
        id="morning_plan",
        replace_existing=True,
    )

    # Evening review
    scheduler.add_job(
        evening_routine,
        CronTrigger(
            hour=config.EVENING_HOUR,
            minute=config.EVENING_MINUTE,
            timezone=config.USER_TIMEZONE,
        ),
        id="evening_review",
        replace_existing=True,
    )

    # Weekly personality update (every Sunday at 11 PM)
    scheduler.add_job(
        weekly_personality_update,
        CronTrigger(
            day_of_week="sun",
            hour=23,
            minute=0,
            timezone=config.USER_TIMEZONE,
        ),
        id="weekly_personality",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started: morning={config.MORNING_HOUR}:{config.MORNING_MINUTE:02d}, "
        f"evening={config.EVENING_HOUR}:{config.EVENING_MINUTE:02d}, "
        f"timezone={config.USER_TIMEZONE}"
    )


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown()
