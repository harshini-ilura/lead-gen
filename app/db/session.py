import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Coroutine

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Sync engine used only by Alembic migrations
sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def run_task(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from a sync Celery task in a fresh event loop.

    Celery tasks call asyncio.run() per invocation, creating a new loop each
    time. The module-level async engine's connection pool binds to whichever
    loop first used it, so a later task on a new loop raises
    "Future attached to a different loop". Disposing the pool after each run
    forces fresh, correctly-bound connections on the next task.
    """
    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await async_engine.dispose()

    return asyncio.run(_wrapped())
