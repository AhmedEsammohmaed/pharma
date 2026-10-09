from typing import Self
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.auth.tokens import parse_access_token
from app.core.config import Settings
from app.core.errors import AppError
from tests.conftest import JWT_SECRET


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["phase"] == 1
    assert "X-Request-Id" in response.headers


def test_liveness_is_independent_of_database(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_requires_postgres(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unconfigured"


class _ReadySession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _statement: object) -> None:
        return None


class _UnavailableSession(_ReadySession):
    async def execute(self, _statement: object) -> None:
        raise SQLAlchemyError("simulated database outage")


def test_readiness_checks_database_connection(client: TestClient) -> None:
    client.app.state.session_factory = _ReadySession
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readiness_reports_database_outage_without_leaking_details(client: TestClient) -> None:
    client.app.state.session_factory = _UnavailableSession
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "simulated database outage" not in response.text


def test_invalid_request_id_is_replaced_with_uuid(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-Id": "not-a-safe-request-id"})
    assert response.status_code == 200
    UUID(response.headers["X-Request-Id"])


def test_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_invalid_token_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_hs256_token_issuer_is_checked() -> None:
    token = jwt.encode(
        {
            "sub": "a75d0fac-15d5-4b31-a8cd-fb14de43c007",
            "aud": "authenticated",
            "iss": "https://attacker.invalid/auth/v1",
            "exp": 2_000_000_000,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    settings = Settings(
        supabase_url="https://correct-project.supabase.co",
        supabase_jwt_secret=JWT_SECRET,
    )
    with pytest.raises(AppError) as exc:
        await parse_access_token(settings, token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_hs256_verification_requires_supabase_issuer_configuration() -> None:
    settings = Settings(supabase_jwt_secret=JWT_SECRET)
    with pytest.raises(AppError) as exc:
        await parse_access_token(settings, "unused")
    assert exc.value.status_code == 503
    assert exc.value.code == "auth_unconfigured"
