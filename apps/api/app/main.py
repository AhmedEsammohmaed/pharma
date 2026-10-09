from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from app.core.config import get_settings
from app.core.errors import AppError, register_error_handlers
from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.db.session import create_engine, create_session_factory
from app.modules.identity.router import router as identity_router
from app.modules.procurement.router import router as procurement_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine) if engine else None
    yield
    if engine is not None:
        await engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "X-Request-Id"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Response:
        candidate = request.headers.get("X-Request-Id", "")
        try:
            request_id = str(uuid.UUID(candidate))
        except (ValueError, AttributeError):
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        token = bind_request_id(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            reset_request_id(token)

    @app.get("/health")
    async def health(request: Request) -> dict:
        database = "configured" if getattr(request.app.state, "session_factory", None) else "missing"
        return {"status": "ok", "phase": 1, "database": database}

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness(request: Request) -> dict[str, object]:
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is None:
            raise AppError(503, "database_unconfigured", "PostgreSQL is not configured")
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.exception("Database readiness check failed")
            raise AppError(503, "database_unavailable", "PostgreSQL is unavailable") from exc
        return {"status": "ready", "checks": {"database": "ok"}}

    app.include_router(identity_router)
    app.include_router(procurement_router)
    return app


app = create_app()
