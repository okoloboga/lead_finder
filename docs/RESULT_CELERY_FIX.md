# LeadCore — Celery/DB Fix Notes

## Problem
After introducing Celery background execution, workers intermittently failed with:

`(sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) cannot perform operation: another operation is in progress`

Observed in `ForkPoolWorker-*` processes while executing program jobs.

## Root Cause
Async SQLAlchemy/asyncpg state was vulnerable to process-boundary issues in Celery worker execution model.

## Applied Fix
1. Database engine process binding:
- Added process-aware engine/session rebinding in `bot/db_config.py`.
- Added worker lifecycle hooks in `bot/celery_app.py` to rebind/dispose engine per worker process.

2. Worker mode stabilization:
- Celery worker runs with `--pool=solo` in `docker-compose.yml`.

3. Task safety:
- Explicit engine process-bound check before task execution in `bot/tasks.py`.

## Additional Runtime Improvements
- LLM-heavy sync functions are executed without blocking the event loop in runtime paths:
  - `qualify_lead_async` wrapper in `modules/qualifier.py`
  - `batch_analyze_chat` called via `asyncio.to_thread` in `modules/members_parser.py`

## Verification
- Unit suite passes locally: `185 passed`.
- CI unit workflow updated to run with `PYTHONPATH=.` to avoid import errors.

## Operational Command
```bash
docker compose up -d --build worker
```
