from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.auth.tokens import AccessTokenClaims, parse_access_token
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import apply_rls_context
from app.modules.identity.store import IdentityStore, SqlIdentityStore

bearer = HTTPBearer(auto_error=False)


async def get_store(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_organization_id: Annotated[UUID | None, Header(alias="X-Organization-Id")] = None,
) -> AsyncIterator[IdentityStore]:
    if getattr(request.app.state, "use_memory_store", False):
        store = getattr(request.app.state, "identity_store", None)
        if store is None:
            raise AppError(503, "store_unavailable", "Identity store is not configured")
        yield store
        return

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "unauthenticated", "Missing bearer token")

    claims = await parse_access_token(settings, credentials.credentials)
    request.state.token_claims = claims
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise AppError(
            503,
            "database_unconfigured",
            "DATABASE_URL is not set. The API cannot load tenant data until Postgres is configured.",
        )
    async with session_factory() as session:
        await apply_rls_context(session, claims.user_id, x_organization_id)
        store = SqlIdentityStore(session)
        try:
            yield store
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> Principal:
    claims: AccessTokenClaims | None = getattr(request.state, "token_claims", None)
    if claims is None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise AppError(401, "unauthenticated", "Missing bearer token")
        claims = await parse_access_token(settings, credentials.credentials)
        request.state.token_claims = claims
    principal = await store.load_principal(claims.user_id, claims.email)
    request.state.principal = principal
    return principal


async def get_authenticated_session(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    x_organization_id: Annotated[UUID | None, Header(alias="X-Organization-Id")] = None,
) -> AsyncIterator[AsyncSession]:
    """Open a transaction after confirming the optional organization belongs to the user."""
    if x_organization_id is not None:
        principal.membership(x_organization_id)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise AppError(503, "database_unconfigured", "PostgreSQL is not configured")
    async with session_factory() as session:
        await apply_rls_context(session, principal.user_id, x_organization_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
