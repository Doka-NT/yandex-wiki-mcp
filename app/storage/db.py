from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator

engine = None
AsyncSessionLocal = None


def init_db(dsn: str) -> None:
    global engine, AsyncSessionLocal
    engine = create_async_engine(dsn, echo=False, pool_pre_ping=True)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
