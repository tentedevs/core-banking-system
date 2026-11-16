# Verified CRP architectural inventory

Reference inspected read-only: `/Users/vicente/credit-risk-platform`.
This inventory describes the actual implementation used for initialization.

| Concern | Verified CRP implementation |
| --- | --- |
| Layout | `src/domain`, `application/use_cases` and `application/queries`, `ports`, `infrastructure`, `api`; separate frontend, database and migrations directories |
| Python/dependencies | `.python-version` 3.12, Python >=3.12, uv, committed uv.lock, `package=false` |
| Domain | Frozen dataclasses, enums, Decimal/UUID values, validation; independent of FastAPI/ORM |
| Application | Constructor-injected use cases; domain-specific exceptions; plain Python query/DTO structures |
| Ports/adapters | typing.Protocol repository/query contracts; in-memory adapters and synchronous SQLAlchemy adapters |
| Mapping | DeclarativeBase ORM rows in persistence/models.py, explicit to_orm/to_domain mapper modules; no ORM entities in domain |
| FastAPI | api.main:create_app(settings), module-level app, lifespan disposal, state-held settings/engine session factory, include_router composition |
| DI | Annotated/Depends providers in api/dependencies.py, per-request sessions, function-scoped yield cleanup; transactional writes, noncommitting reads |
| Settings | pydantic-settings BaseSettings, root .env, process environment priority, ignored extras, SecretStr URL, safe validation errors; separate database/.env |
| Persistence | SQLAlchemy 2, psycopg 3, lazy engine, pool_pre_ping, hide_parameters, five-second timeout, expire_on_commit=False |
| PostgreSQL | postgres:16, separate credit-risk-db Compose project, localhost:5432, healthcheck, environment credentials, independent named persistent volume |
| API Docker | Separate credit-risk-platform-api Compose project on localhost:8000; Python 3.12 slim and uv 0.12.23, non-root user |
| Alembic | migrations/env.py loads Settings and Base metadata, external connection support; explicit init/migrate/current/history utilities, no automatic startup migrations |
| Schemas | Pydantic v2 HTTP schemas, extra=forbid requests, from_attributes responses, Decimal constraints; separate from domain dataclasses |
| Errors/logging | Domain/use-case errors translated to 404/409/422 in routers; generic SQLAlchemy 503 handler; redacted CLI database failures; standard Uvicorn logging, no custom logging configuration |
| Health | GET /health returns status=ok for API liveness; no DB readiness endpoint |
| Tests | pytest, tests/unit and tests/integration, httpx/TestClient, dedicated _test database, unique integration schemas, marker and pythonpath configuration |
| Tooling | Ruff E/F/I/UP/B, Ruff formatting at 100 columns, strict mypy with Pydantic plugin; no Black/pre-commit configuration found |
| Make | uv install/dev, separate API and DB lifecycle, DB connectivity/migrations/smoke checks, lint/format/types/unit/integration tests; separate frontend commands |
| Documentation | Main README, database README, integration-test README, frontend README, AGENTS.md |
| CI | GitHub Actions checkout v4/setup-uv v6, uv 0.12.23, Python 3.12, locked install, Ruff lint/format, mypy, unit tests |

CBS preserves these conventions without copying credit-risk business code.
The CRP ingestion package and frontend are not needed for this initialization.
Only package docstrings reserve domain/application/port layers; no future
business-specific folders or placeholder contracts are introduced.

## Implementation plan applied

1. Reproduce project metadata, lockfile versions, Python pin, backend tooling,
   Dockerfile, Make commands, and backend CI.
2. Preserve src package boundaries; adapt the application factory and generic
   session dependency without CRP repository providers or business routers.
3. Reuse settings, lazy engines, session factories, redacted connectivity CLI,
   and explicit Alembic utility; retain only an empty DeclarativeBase metadata.
4. Configure independent database/API Compose projects, ports, credentials and
   volume; adapt the isolated database lifecycle test.
5. Add only infrastructure unit/integration tests and documentation.
