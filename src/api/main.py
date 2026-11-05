"""FastAPI composition root; database lifecycle and migrations remain explicit."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from auth_client import AuthServiceClient
from auth_client.fastapi_dependencies import build_current_actor_dependency
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from api.authentication import require_banking_admin
from api.routers.accounts import router as accounts_router
from api.routers.customer_onboarding import router as customer_onboarding_router
from api.routers.customer_reads import router as customer_reads_router
from api.routers.customer_transfers import router as customer_transfers_router
from api.routers.internal_registration import router as internal_registration_router
from api.routers.me import router as me_router
from api.routers.transactions import router as transactions_router
from application.account_access_policy import CustomerAccessDenied
from application.transaction_posting import AccountNotActive
from application.use_cases.get_account import AccountNotFound
from application.use_cases.get_transaction import TransactionNotFound
from domain.account.exceptions import InvalidAccountData, InvalidAccountStateTransition
from domain.account_balance.exceptions import InsufficientFunds, InvalidAccountBalanceData
from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.settings import Settings
from ports.account_repository import AccountNumberConflict
from ports.balance_repository import BalanceCurrencyMismatch, BalanceNotFound
from ports.transaction_repository import IdempotencyConflict

logger = logging.getLogger("uvicorn.error")


def create_app(settings: Settings | None = None, *, internal: bool = False) -> FastAPI:
    settings = settings if settings is not None else Settings()
    auth_client = (
        AuthServiceClient(
            base_url=settings.auth_service_internal_url,
            service_id=settings.auth_service_id,
            service_credential=settings.auth_service_credential.get_secret_value(),
            application_code=settings.auth_application_code,
            timeout=settings.auth_request_timeout,
            allow_insecure_http=settings.auth_allow_insecure_http,
        )
        if settings.auth_service_internal_url and settings.auth_service_credential
        else None
    )
    engine: Engine | None = None
    if settings.persistence_backend == "postgres":
        engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            try:
                if auth_client is not None:
                    auth_client.close()
            finally:
                if engine is not None:
                    engine.dispose()

    app = FastAPI(
        title="Core Banking System",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if internal else "/docs",
        redoc_url=None if internal else "/redoc",
        openapi_url=None if internal else "/openapi.json",
    )
    app.state.settings = settings
    app.state.auth_client = auth_client
    app.state.current_actor_dependency = (
        build_current_actor_dependency(
            client=auth_client, cookie_name=settings.auth_session_cookie_name
        )
        if auth_client is not None
        else None
    )
    if settings.auth_debug_endpoint_enabled:
        from api.routers.auth_diagnostics import router as auth_diagnostics_router

        app.include_router(auth_diagnostics_router)
    app.state.session_factory = create_session_factory(engine) if engine is not None else None
    if internal:
        if settings.registration_service_credential:
            app.include_router(internal_registration_router)
    else:
        app.include_router(me_router)
        app.include_router(customer_reads_router)
        app.include_router(customer_transfers_router)
        app.include_router(customer_onboarding_router)
        app.include_router(accounts_router, dependencies=[Depends(require_banking_admin)])
        app.include_router(transactions_router, dependencies=[Depends(require_banking_admin)])

    @app.exception_handler(CustomerAccessDenied)
    async def customer_access_denied(request: Request, exc: CustomerAccessDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(TransactionNotFound)
    async def transaction_not_found(request: Request, exc: TransactionNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Transaction not found"})

    @app.exception_handler(InsufficientFunds)
    async def insufficient_funds(request: Request, exc: InsufficientFunds) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Insufficient funds"})

    @app.exception_handler(AccountNotActive)
    async def account_not_active(request: Request, exc: AccountNotActive) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Account must be ACTIVE"})

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(request: Request, exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Idempotency key conflicts with the original request"},
        )

    @app.exception_handler(BalanceNotFound)
    async def balance_not_initialized(request: Request, exc: BalanceNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=409, content={"detail": "Account balance is not initialized"}
        )

    @app.exception_handler(BalanceCurrencyMismatch)
    async def currency_mismatch(request: Request, exc: BalanceCurrencyMismatch) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": "Currency does not match the account"}
        )

    @app.exception_handler(InvalidAccountBalanceData)
    async def invalid_balance(request: Request, exc: InvalidAccountBalanceData) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": "Operation would produce an invalid balance"}
        )

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
