# Initialization report

The Core Banking System foundation is implemented under
`/Users/vicente/core-banking/core-banking-system`. The reference repository at
`/Users/vicente/credit-risk-platform` was inspected read-only. Its Git status
before and after was unchanged: only its pre-existing untracked `.vscode/`
directory was reported. No CRP files were modified or imported by CBS.

## Created-file inventory and final tree

All source/configuration/documentation files below were created for CBS.
Generated virtual environments, caches, and ignored local `.env` files are omitted.
The safe development environment examples were copied to local `.env` and
database/.env using `make env-init`, which does not overwrite existing files.

```text
core-banking-system/
├── .github/
│   └── workflows/
│       └── ci.yml
├── database/
│   ├── .env.example
│   ├── README.md
│   ├── compose.yml
│   └── test-service.sh
├── docs/
│   ├── architecture-inventory.md
│   └── initialization-report.md
├── migrations/
│   ├── versions/
│   │   └── README.md
│   ├── env.py
│   └── script.py.mako
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py
│   │   └── main.py
│   ├── application/
│   │   └── __init__.py
│   ├── domain/
│   │   └── __init__.py
│   ├── infrastructure/
│   │   ├── persistence/
│   │   │   ├── __init__.py
│   │   │   ├── check_db.py
│   │   │   ├── database.py
│   │   │   ├── migrate.py
│   │   │   └── models.py
│   │   ├── __init__.py
│   │   └── settings.py
│   └── ports/
│       └── __init__.py
├── tests/
│   ├── integration/
│   │   ├── README.md
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_database.py
│   │   └── test_foundation.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_application.py
│   │   ├── test_migrations.py
│   │   └── test_settings.py
│   └── __init__.py
├── .dockerignore
├── .env.example
├── .gitignore
├── .python-version
├── AGENTS.md
├── Dockerfile
├── Makefile
├── README.md
├── alembic.ini
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

## Architectural decisions

- Retain CRP's Python 3.12, uv nonpackaged src layout, absolute top-level imports,
  and every locked third-party dependency version.
- Retain the domain/application/ports/infrastructure/API boundaries without
  creating business-specific abstractions. Package docstrings establish the
  existing layer structure without empty placeholder files.
- Reuse the settings validation, lazy synchronous SQLAlchemy engines,
  request-scoped transactional sessions, explicit Alembic operations, generic
  redacted infrastructure errors, and standard Uvicorn logging.
- Keep /health as liveness only; actual PostgreSQL connectivity is checked by
  the SELECT 1 utility. Do not add a readiness claim or fake connectivity.
- Initialize Alembic with empty DeclarativeBase metadata and no revisions.
  Adapt head verification to accept an empty revision set. No business schema
  is created; Alembic may maintain its own empty version table.
- Preserve dedicated-database/unique-schema integration isolation and the
  separate database Compose lifecycle/smoke-test pattern.
- Reproduce backend CI checks; add format-check to make check so it agrees with CI.
- Exclude frontend, credit-risk behavior, customers, all banking domain models,
  ingestion, seeds, and dataset dependencies.

## Configuration differences

| Setting | CRP default | CBS default |
| --- | --- | --- |
| Project/package metadata | credit-risk-platform | core-banking-system |
| FastAPI title | Credit Risk Platform | Core Banking System |
| Host API port | 8000 | 8001 |
| API Compose project | credit-risk-platform-api | core-banking-system-api |
| DB Compose project | credit-risk-db | core-banking-db |
| Host PostgreSQL port | 5432 | 5433 |
| DB name/user | creditrisk | corebanking |
| Persistent volume | credit-risk-platform_postgres_data | core-banking-system_postgres_data |
| Dedicated integration DB example | credit_risk_test | core_banking_test |
| Migration history | CRP initial business schema | Empty history, no business tables |
| Memory mode | In-memory business repositories | Connectivity disabled, no business repositories |
| API Compose environment | Default memory mode | Explicitly passes persistence settings and URL |

Both databases bind to 127.0.0.1 and use separate credentials/configuration and
persistent volumes. Internal container ports remain 8000/5432, as in CRP.
Names and default host ports were checked statically for independence; the two
systems were not launched simultaneously.

## Starting CBS

```sh
cd /Users/vicente/core-banking/core-banking-system
make env-init
make install
make dev
```

API health: http://localhost:8001/health. This starts without PostgreSQL or CRP.
For PostgreSQL (Docker with Compose v2 required):

```sh
make db-up
make db-check
make db-init
PERSISTENCE_BACKEND=postgres make dev
```

Stop the API with Ctrl+C; stop PostgreSQL with make db-down (preserves data).
The README covers independent API Docker execution and container URL differences.

## Validation actually executed

| Check | Result |
| --- | --- |
| Locked dependency installation (uv sync --locked) | Passed after sandbox network approval; Python 3.12.15, 40 installed packages |
| Third-party lockfile comparison against CRP | Passed, same versions |
| make check | Passed: Ruff lint, Ruff format, strict mypy (13 source files), 24 unit tests |
| Actual Uvicorn startup on localhost:8001 | Passed after sandbox port-binding approval |
| Actual HTTP /health and /openapi.json | 200; correct application title; only /health in API paths |
| Actual Uvicorn shutdown | Passed, lifespan shutdown completed |
| make db-history | Passed, empty history |
| YAML parsing of DB/API Compose and CI | Passed; this is not Docker Compose validation |
| sh -n database/test-service.sh | Passed |
| make test-integration | Collected five tests; all skipped because TEST_DATABASE_URL is absent |
| make db-config, make db-up | Could not run: Docker executable is not installed |
| make db-test | Could not run: Docker executable is not installed |
| make db-check-sqlalchemy | Failed as expected with no running PostgreSQL; generic error returned without credentials |

The unit suite emits one deprecation warning from the inherited Starlette/httpx
TestClient dependency combination. It does not fail tests; dependencies were kept
aligned with CRP rather than adding an alternate HTTP client.

## Remaining validation

The full Definition of Done remains pending live PostgreSQL/Docker validation.
Docker image builds, Compose validation, database health/startup/persistence,
SQLAlchemy success against PostgreSQL, online Alembic empty-history execution,
and simultaneous CRP/CBS runtime operation could not be verified on this host.
No successful connectivity was mocked or claimed.

With Docker available, run make db-up, make db-check, make db-init, and make db-test.
Create a dedicated core_banking_test database and set TEST_DATABASE_URL as described
in tests/integration/README.md, then run make test-integration. These tests include
real connectivity, repeated empty migrations, request sessions, and commit/rollback.
