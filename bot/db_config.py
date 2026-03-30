import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Construct the database URL from environment variables
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_USER = os.getenv("POSTGRES_USER", "myuser")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "mypassword")
DB_NAME = os.getenv("POSTGRES_DB", "leadcore_db")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


# Track process ownership to avoid reusing asyncpg state across Celery prefork workers.
_ENGINE_PID: int | None = None


def _create_engine():
    return create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )


# Create an async engine and session maker
engine = _create_engine()
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
_ENGINE_PID = os.getpid()


def ensure_engine_process_bound() -> bool:
    """Rebind engine/sessionmaker if current process differs from creator PID.

    This protects Celery prefork workers from inheriting parent-process
    asyncpg state, which can cause "another operation is in progress" errors.

    Returns:
        True if engine was rebound, otherwise False.
    """
    global engine, _ENGINE_PID

    pid = os.getpid()
    if _ENGINE_PID == pid:
        return False

    engine = _create_engine()
    async_session.configure(bind=engine)
    _ENGINE_PID = pid
    return True


def rebind_engine() -> None:
    """Always recreate engine and sessionmaker.

    Must be called before each asyncio.run() in Celery tasks.
    asyncio.run() creates a new event loop each invocation; asyncpg pool
    connections are tied to the previous (now closed) loop, causing
    'Future attached to a different loop' on reuse.
    """
    global engine, _ENGINE_PID
    engine = _create_engine()
    async_session.configure(bind=engine)
    _ENGINE_PID = os.getpid()


async def dispose_engine() -> None:
    """Best-effort async engine disposal."""
    await engine.dispose()


def dispose_engine_sync() -> None:
    """Sync wrapper for contexts where awaiting is not convenient."""
    try:
        asyncio.run(dispose_engine())
    except RuntimeError:
        # In case we're already inside an event loop.
        pass


async def get_session() -> AsyncSession:
    """Dependency injection for getting a database session."""
    async with async_session() as session:
        yield session
