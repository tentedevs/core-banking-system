"""FastAPI composition root; database lifecycle and migrations remain explicit."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from api.routers.accounts import router as accounts_router
from application.use_cases.get_account import AccountNotFound
from domain.account.exceptions import InvalidAccountData, InvalidAccountStateTransition
from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.settings import Settings
from ports.account_repository import AccountNumberConflict

logger = logging.getLogger("uvicorn.error")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    engine: Engine | None = None
    if settings.persistence_backend == "postgres":
        engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="Core Banking System", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = create_session_factory(engine) if engine is not None else None
    app.include_router(accounts_router)

    @app.exception_handler(AccountNotFound)
    async def account_not_found(request: Request, exc: AccountNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})

    @app.exception_handler(InvalidAccountStateTransition)
    async def invalid_transition(
        request: Request, exc: InvalidAccountStateTransition
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AccountNumberConflict)
    async def number_conflict(request: Request, exc: AccountNumberConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Account number already in use"})

    @app.exception_handler(InvalidAccountData)
    async def invalid_account(request: Request, exc: InvalidAccountData) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Database operation unavailable"})

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected application failure", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/health")
    def health() -> dict[str, str]:
        """API liveness only. Use the explicit database check for connectivity."""
        return {"status": "ok"}

    return app


app = create_app()
