import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from bot.db_config import DATABASE_URL

logger = logging.getLogger(__name__)

# APScheduler requires a sync DB URL for its job store
_SYNC_DB_URL = DATABASE_URL.replace("+asyncpg", "")

jobstores = {
    "default": SQLAlchemyJobStore(url=_SYNC_DB_URL)
}

scheduler = AsyncIOScheduler(jobstores=jobstores)


def schedule_program_job(program_id: int, chat_id: int, schedule_time: str) -> None:
    """Schedules (or reschedules) a daily cron job for a program.

    Uses serializable kwargs only (no Bot object) so APScheduler can
    persist the job in PostgreSQL across restarts.
    """
    from bot.services.program_runner import run_program_job

    hour, minute = schedule_time.split(":")
    scheduler.add_job(
        run_program_job,
        trigger="cron",
        hour=int(hour),
        minute=int(minute),
        id=f"program_{program_id}",
        replace_existing=True,
        kwargs={"program_id": program_id, "chat_id": chat_id},
        misfire_grace_time=3600,  # allow up to 1h late start
    )
    logger.info(
        f"[Scheduler] Job scheduled: program_id={program_id}, "
        f"chat_id={chat_id}, time={schedule_time}"
    )


def remove_program_job(program_id: int) -> None:
    """Removes a scheduled job for a program."""
    job_id = f"program_{program_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"[Scheduler] Job removed: program_id={program_id}")
