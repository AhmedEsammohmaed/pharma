from app.core.config import Settings
from app.db.session import create_engine, to_async_dsn


def test_create_engine_prefers_restricted_database_url(monkeypatch) -> None:
    captured: dict[str, object] = {}
    engine = object()

    def fake_create_async_engine(url: str, **options: object) -> object:
        captured["url"] = url
        captured["options"] = options
        return engine

    monkeypatch.setattr("app.db.session.create_async_engine", fake_create_async_engine)
    settings = Settings(
        database_url="postgresql://superuser:secret@db.example/postgres",
        database_url_rls="postgresql://pharma_api:secret@db.example/postgres",
    )

    assert create_engine(settings) is engine
    assert captured["url"] == "postgresql+asyncpg://pharma_api:secret@db.example/postgres"
    assert captured["options"] == {"pool_pre_ping": True}


def test_sync_postgres_dsn_is_normalized_for_asyncpg() -> None:
    assert to_async_dsn("postgres://db.example/pharma") == "postgresql+asyncpg://db.example/pharma"
