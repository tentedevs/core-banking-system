"""FastAPI composition root; database lifecycle and migrations remain explicit."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.settings import Settings


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

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database operation unavailable"})

    @app.get("/health")
    def health() -> dict[str, str]:
        """API liveness only. Use the explicit database check for connectivity."""
        return {"status": "ok"}

    return app


app = create_app()
