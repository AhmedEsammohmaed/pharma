from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import httpx
import jwt

from app.core.config import Settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    email: str | None
    role: str | None


def _decode_hs256(token: str, secret: str, issuer: str | None) -> dict:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="authenticated",
        issuer=issuer,
        options={"require": ["sub", "exp"]},
    )


async def _introspect_supabase(settings: Settings, token: str) -> dict:
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise AppError(401, "unauthenticated", "Authentication is not configured")
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.supabase_publishable_key,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("Supabase Auth introspection request failed")
        raise AppError(503, "auth_provider_unavailable", "Authentication provider is unavailable") from exc
    if response.status_code in {401, 403}:
        raise AppError(401, "unauthenticated", "Invalid or expired access token")
    if response.status_code != 200:
        logger.warning("Supabase Auth introspection returned status %s", response.status_code)
        raise AppError(503, "auth_provider_unavailable", "Authentication provider is unavailable")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppError(503, "auth_provider_unavailable", "Authentication provider returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise AppError(503, "auth_provider_unavailable", "Authentication provider returned an invalid response")
    return payload


async def parse_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    payload: dict
    if settings.supabase_jwt_secret:
        if not settings.supabase_url:
            raise AppError(503, "auth_unconfigured", "SUPABASE_URL is required for local JWT verification")
        try:
            issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
            payload = _decode_hs256(token, settings.supabase_jwt_secret, issuer)
        except jwt.PyJWTError as exc:
            raise AppError(401, "unauthenticated", "Invalid or expired access token") from exc
    else:
        payload = await _introspect_supabase(settings, token)

    sub = payload.get("sub") or payload.get("id")
    if not sub:
        raise AppError(401, "unauthenticated", "Invalid access token")
    try:
        user_id = UUID(str(sub))
    except ValueError as exc:
        raise AppError(401, "unauthenticated", "Invalid access token subject") from exc

    email = payload.get("email")
    if not email:
        user = payload.get("user")
        if isinstance(user, dict):
            email = user.get("email")
    return AccessTokenClaims(user_id=user_id, email=email, role=payload.get("role"))
