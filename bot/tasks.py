import asyncio
import logging

from bot.celery_app import celery_app
from bot.db_config import rebind_engine
from bot.services.program_runner import run_program_job
from modules.telegram_client import TelegramAuthManager

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="bot.tasks.run_program_job_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def run_program_job_task(self, program_id: int, chat_id: int) -> dict:
    """Execute one program run in worker process."""
    # asyncio.run() creates a new event loop each call.
    # Reset asyncpg pool (bound to old loop) and Telethon client (same issue).
    rebind_engine()
    TelegramAuthManager.force_reset()
    logger.info(
        f"[CELERY] Running program job task: program_id={program_id}, chat_id={chat_id}"
    )
    asyncio.run(run_program_job(program_id, chat_id))
    return {"program_id": program_id, "chat_id": chat_id}


def enqueue_program_job(program_id: int, chat_id: int) -> str:
    """Enqueue a program job and return task id."""
    task = run_program_job_task.delay(program_id=program_id, chat_id=chat_id)
    return task.id
