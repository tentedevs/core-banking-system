# core-banking-system

Independent Core Banking System (CBS) foundation, aligned with the verified
Credit Risk Platform (CRP) backend architecture. This initialization implements
application and persistence infrastructure plus the Accounts domain and persistence model.
See [Accounts domain](docs/accounts-domain.md) for its invariants and operations.
See [Accounts persistence](docs/accounts-persistence.md) for Phase 2.
See [Accounts repository](docs/accounts-repository.md) for Phase 3.
See [Accounts application](docs/accounts-application.md) for Phase 4.
See [Accounts REST API](docs/accounts-api.md) for Phase 5.
See [CBS frontend](frontend/README.md) for the independent Accounts interface.

## Requirements and stack

Python 3.12+ (development pin: 3.12), uv with committed `uv.lock`, FastAPI,
Pydantic v2 and pydantic-settings, synchronous SQLAlchemy 2, psycopg 3,
PostgreSQL 16, and Alembic. Development checks use pytest/httpx, Ruff, and strict
mypy. Docker with Compose v2 is required for the provided database service.
`make` provides the development commands. CI pins uv 0.12.23, matching CRP.

## Development setup

From this directory:

```sh
make env-init
make install
make dev
```

`env-init` creates `.env` and `database/.env` from safe development examples
only when missing. Adjust credentials in both files together. Never use the
example passwords outside local development. Both environment files are ignored.
Environment variables override `.env` settings; unknown settings are ignored.

API: http://localhost:8001/health — interactive documentation:
http://localhost:8001/docs. Stop Uvicorn with Ctrl+C.

The CRP-compatible default `PERSISTENCE_BACKEND=memory` disables database
connectivity; CBS has no in-memory business stores. It allows the infrastructure
skeleton to start without PostgreSQL. Accounts routes then return 503; health
and OpenAPI remain available. Persisted Accounts operations require postgres mode.
`DATABASE_MODE` is retained for standalone database utilities; the API selects
connectivity with `PERSISTENCE_BACKEND`. Both accept `memory` or `postgres`.
A supplied DATABASE_URL must use `postgresql+psycopg` and name a database.

## PostgreSQL and migrations

```sh
make env-init
make db-up
make db-status
make db-check
make db-init
make db-current
PERSISTENCE_BACKEND=postgres make dev
```

The independent Compose project `core-banking-db` exposes PostgreSQL only on
`127.0.0.1:5433`. The development database/user are `corebanking`; the default
persistent volume is `core-banking-system_postgres_data`. CRP's default ports
5432 and 8000 are left available. Host port overrides must be reflected in
DATABASE_URL. Override DB_ENV to use another database environment file.

`make db-down` stops PostgreSQL and preserves data. `make db-restart`,
`make db-ready`, `make db-logs`, and `make db-shell` provide service management.
See [database/README.md](database/README.md).

`make db-init` and `make db-migrate` explicitly run Alembic and verify the
installed revision set; `make db-history` shows the history. Revision
`0001_create_accounts` creates `banking.accounts`, its constraints and customer
index, plus Alembic's revision bookkeeping. The application never
runs migrations or creates tables during startup.

`/health` reports API **liveness only**, including when PostgreSQL is unavailable.
It does not claim database readiness. `make db-ready` checks pg_isready;
`make db-check-sqlalchemy` executes a real SELECT 1 using the configured credentials.
PostgreSQL mode never falls back to memory when a connection fails.

## API container

```sh
make up
make down
```

The independent `core-banking-system-api` Compose project publishes
`127.0.0.1:8001`. It builds the same Python/uv runtime as CRP and starts without a
database by default. It never starts the separate database Compose project.
For PostgreSQL from Docker Desktop, supply a DATABASE_URL using
`host.docker.internal:5433` instead of localhost and set
PERSISTENCE_BACKEND=postgres. Linux hosts need an explicitly reachable database
address or host-gateway configuration. The default root URL is for host-run Uvicorn.

## Architecture and repository structure

```text
.github/workflows/ci.yml           # CRP-style backend checks
.python-version, pyproject.toml, uv.lock
.env.example, .gitignore, .dockerignore
AGENTS.md, Dockerfile, Makefile, docker-compose.yml, alembic.ini
README.md
database/
  .env.example, compose.yml, README.md, test-service.sh
docs/
  architecture-inventory.md
  initialization-report.md
migrations/
  env.py, script.py.mako
  versions/0001_create_accounts.py
src/
  domain/
    __init__.py
    account/                     # Pure Accounts domain
      __init__.py, entities.py, enums.py, exceptions.py
  application/
    __init__.py, account_messages.py, account_numbers.py
    use_cases/                   # Six Account application operations
  ports/
    __init__.py, account_repository.py
    account_unit_of_work.py, account_number_generator.py
  api/
    __init__.py, main.py, dependencies.py
    routers/__init__.py, routers/accounts.py
    schemas/__init__.py, schemas/account.py
  infrastructure/
    __init__.py, settings.py
    persistence/
      __init__.py, database.py, models.py, check_db.py, migrate.py
      mappers/__init__.py, mappers/account_mapper.py
      repositories/__init__.py, repositories/account_repository.py
      account_unit_of_work.py
tests/
  __init__.py
  unit/
    __init__.py, conftest.py
    test_application.py, test_settings.py, test_migrations.py, test_account.py
    test_account_mapper.py
    test_account_repository.py
    test_account_use_cases.py
    test_accounts_api.py
  integration/
    __init__.py, README.md, conftest.py
    test_database.py, test_foundation.py
    test_account_persistence.py, test_account_migrations.py
    test_account_repository.py
    test_account_use_cases.py
    test_accounts_api.py
```

CRP's top-level `src` packages and absolute imports are preserved; uv's
`package=false` convention is retained. Uvicorn uses `--app-dir src`; Python
utilities use `PYTHONPATH=src`; pytest configures that path in pyproject.toml.
There is no import, shared package, or runtime dependency on CRP.

`create_app(settings)` owns a lazy engine/session factory and disposes the
engine on shutdown. Engines use `pool_pre_ping`, a five-second connection timeout,
and hidden SQL parameters; sessions use `expire_on_commit=False`. The FastAPI
session dependency remains available for infrastructure probes. Accounts uses
the application Unit of Work with the same session factory; write transactions
complete before the route returns, and reads close without committing.
SQLAlchemy errors return a generic 503 without connection
or SQL details. Logging uses the existing Uvicorn defaults, as in CRP.

Future domain dataclasses belong in `domain/`, constructor-injected use cases in
`application/use_cases/`, Protocol contracts in `ports/`, and adapters in
`infrastructure/`. ORM rows will remain separate from domain entities, with
explicit `to_orm`/`to_domain` mappers in `infrastructure/persistence/mappers/`.
HTTP routers and Pydantic request/response schemas follow CRP's `api/routers/`
and `api/schemas/` organization. CBS's own React/TypeScript frontend lives in
`frontend/` and calls only the CBS API.

See the [verified reference inventory](docs/architecture-inventory.md) and
[initialization report](docs/initialization-report.md) for inherited decisions,
configuration differences, the created-file inventory, and validation results.

## Tests and development checks

The independent CBS frontend runs on **127.0.0.1:5174**, with its development
proxy targeting the CBS backend on **127.0.0.1:8001**. From this project root:

```sh
nvm use
make frontend-install
make frontend-dev
```

Keep `PERSISTENCE_BACKEND=postgres make dev` running in a separate terminal,
after `make db-up` and `make db-init`. The UI manages Accounts only and does not
require CRP. See [frontend setup and capabilities](frontend/README.md).

```sh
make check                  # Ruff lint + format check, strict mypy, unit tests
make format                 # Ruff formatting
make test-verbose
make test-integration       # Requires a dedicated TEST_DATABASE_URL
make db-test                # Isolated Docker lifecycle/persistence smoke test
make frontend-typecheck
make frontend-lint
make frontend-test
make frontend-build
```

Unit tests require neither CRP nor PostgreSQL. Integration tests perform real
SQLAlchemy connections, account persistence and constraints, reversible migrations,
API session checks, and commit/rollback tests in disposable `_test` databases.
They skip when TEST_DATABASE_URL is absent and fail on invalid configured
connections. See [tests/integration/README.md](tests/integration/README.md).

## Scope and planned capabilities

Implemented: Accounts domain with the SAVINGS_ACCOUNT product, settings validation,
FastAPI startup/shutdown and liveness,
SQLAlchemy engines/sessions, PostgreSQL Compose, Account ORM and bidirectional
mapper, an Accounts Alembic migration, AccountRepository port and SQLAlchemy
adapter, six Account use cases, an explicit application transaction boundary,
six Accounts REST endpoints, development checks, and infrastructure/API tests.

Planned only: customer integration, account ownership, current accounts,
balances, deposits, withdrawals, internal transfers, movements, double-entry
ledger, and transaction history. No Customer, Transaction, Ledger, or
Balance business models, repositories, use cases, endpoints, or tables exist.
The Accounts domain provides an immutable Account entity, ACTIVE/BLOCKED state
transitions, and historical reconstruction including CLOSED accounts. Account
closure remains deferred. The Account repository uses an injected
Session; application writes commit through the AccountUnitOfWork port and its
SQLAlchemy adapter. Read operations do not commit.

Customer identity and service ownership will be designed separately. No shared
physical database, duplicated Customer entity, or synchronization is assumed.
Ports and infrastructure boundaries allow a future explicit integration.

Data preparation, cleaning, normalization, and Berka-specific mapping happen
outside this repository. There are no datasets, ingestion adapters, ETL, seeds,
or data-processing dependencies.
