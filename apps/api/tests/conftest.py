from collections.abc import Iterator
from time import time
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.modules.identity.store import MemoryIdentityStore

JWT_SECRET = "pharmaintelligence-test-secret-at-least-32-bytes"


@pytest.fixture
def store() -> MemoryIdentityStore:
    return MemoryIdentityStore()


@pytest.fixture
def app(store: MemoryIdentityStore):
    get_settings.cache_clear()
    application = create_app()
    application.state.use_memory_store = True
    application.state.identity_store = store
    application.state.session_factory = None
    return application


@pytest.fixture
def client(app, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def make_token(user_id: str, email: str = "user@example.com") -> str:
    now = int(time())
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "role": "authenticated",
            "aud": "authenticated",
            "iss": "https://test-project.supabase.co/auth/v1",
            "iat": now,
            "exp": now + 3600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def auth_header(user_id: str, email: str = "user@example.com") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id, email)}"}


@pytest.fixture
def user_a_id():
    return uuid4()


@pytest.fixture
def user_b_id():
    return uuid4()
