import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text, select

from bot.db_config import engine, async_session
from bot.handlers import start, program_create, program_list, program_view, auth, lead_viewer, program_edit, pains_handler
from bot.middleware.db_session import DbSessionMiddleware
from bot.models.base import Base
from bot.models.program import Program, ProgramChat
from bot.models.lead import Lead
from bot.models.pain import Pain, PainCluster, GeneratedPost
from bot.scheduler import scheduler, schedule_program_job


async def create_tables() -> None:
    """Creates all tables in the database if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_migrations() -> None:
    """Applies incremental schema changes for columns added after initial creation."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE leads ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'new'"
        ))
        await conn.execute(text(
            "ALTER TABLE programs ADD COLUMN IF NOT EXISTS owner_chat_id BIGINT"
        ))
        # Drop old global unique constraint on telegram_username (if it exists)
        await conn.execute(text(
            "ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_telegram_username_key"
        ))
        # Add per-program unique constraint (idempotent via DO block)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_lead_program_username'
                ) THEN
                    ALTER TABLE leads
                        ADD CONSTRAINT uq_lead_program_username
                        UNIQUE (program_id, telegram_username);
                END IF;
            END
            $$
        """))


async def restore_scheduled_jobs() -> None:
    """Re-registers APScheduler jobs for programs that have no active job.

    APScheduler persists jobs in PostgreSQL, so after a normal restart they
    are already there. This function handles the case where the jobstore was
    reset or a program was created before scheduling was implemented.
    """
    async with async_session() as session:
        query = select(Program).where(Program.owner_chat_id.isnot(None))
        programs = (await session.execute(query)).scalars().all()

    for program in programs:
        job_id = f"program_{program.id}"
        if not scheduler.get_job(job_id):
            schedule_program_job(program.id, program.owner_chat_id, program.schedule_time)
            logging.info(
                f"[Startup] Restored job for program '{program.name}' (id={program.id})"
            )


async def main(bot_token: str) -> None:
    """Bot entry point."""
    await create_tables()
    await run_migrations()

    bot = Bot(token=bot_token, parse_mode="HTML")
    dp = Dispatcher(
        storage=MemoryStorage(),
        bot=bot,
        scheduler=scheduler,
    )

    dp.update.middleware(DbSessionMiddleware(session_pool=async_session))

    dp.include_router(start.router)
    dp.include_router(program_create.router)
    dp.include_router(program_list.router)
    dp.include_router(program_view.router)
    dp.include_router(program_edit.router)
    dp.include_router(auth.router)
    dp.include_router(lead_viewer.router)
    dp.include_router(pains_handler.router)

    dp.shutdown.register(scheduler.shutdown)

    scheduler.start()
    await restore_scheduled_jobs()

    logging.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
