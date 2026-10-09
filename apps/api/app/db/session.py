from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def to_async_dsn(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def create_engine(settings: Settings) -> AsyncEngine | None:
    # Prefer the restricted request role so PostgreSQL RLS remains a second boundary.
    database_url = settings.database_url_rls or settings.database_url
    if not database_url:
        return None
    return create_async_engine(to_async_dsn(database_url), pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def apply_rls_context(
    session: AsyncSession,
    user_id: UUID | None,
    organization_id: UUID | None,
) -> None:
    await session.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id) if user_id else ""},
    )
    await session.execute(
        text("SELECT set_config('app.organization_id', :oid, true)"),
        {"oid": str(organization_id) if organization_id else ""},
    )


async def session_with_rls(
    factory: async_sessionmaker[AsyncSession],
    user_id: UUID | None,
    organization_id: UUID | None,
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        await apply_rls_context(session, user_id, organization_id)
        yield session
