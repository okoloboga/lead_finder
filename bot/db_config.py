import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Construct the database URL from environment variables
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_USER = os.getenv("POSTGRES_USER", "myuser")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "mypassword")
DB_NAME = os.getenv("POSTGRES_DB", "leadcore_db")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create an async engine and session maker
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    """Dependency injection for getting a database session."""
    async with async_session() as session:
        yield session
