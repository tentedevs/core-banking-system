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
See [Transactions domain](docs/transactions-domain.md) for the domain-only first
phase of Transactions. The MVP uses a transactional AccountBalance projection
rather than a double-entry ledger.
See [Transactions persistence](docs/transactions-persistence.md) for the separate
Phase 2 ORM, mappers and incremental migration.
See [Account balances](docs/account-balances.md) for Phase 4's internal balance
coordination, atomic zero initialization and controlled historical opening policy.

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
    transaction/                 # Pure transactions and account movements
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

Transactions adds immutable BankingTransaction and AccountMovement domain
entities, ORM models, bidirectional mappers and an incremental migration for
banking.transactions and banking.account_movements. AccountBalance and explicit
opening metadata now support internal transaction-safe balance coordination.
New Account creation initializes its zero balance atomically. Public posting,
deposits, withdrawals, internal transfers and transaction history remain deferred.
The MVP coordinates projections with PostgreSQL ACID transactions and will not implement a
double-entry ledger. Customer integration, account ownership and additional
products remain future work; there is no Customer model.
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

Transactions application operations (Phase 5): see [atomic posting and durable idempotency](docs/transaction-use-cases.md). The [Transactions REST API](docs/transactions-api.md) exposes these operations in Phase 6.

CBS frontend Transactions management (Phase 2): see [frontend operations and idempotency](frontend/README.md#transactions).

Customer Banking local DEMO (frontend Phase 3) is available at `/banking` alongside
the existing administrative console. See [customer experience and contract limits](frontend/README.md#customer-banking--phase-3-local-demo).

## Auth integration — Phase 1

CBS consumes the independent `auth-client-python[fastapi]` package from
`../../login-auth-service/packages/auth-client-python` as an editable uv dependency.
Keep the login-auth-service repository at that relative location, then run
`uv sync --locked`. No auth source is copied into CBS.

Configure backend-only environment values (never VITE variables):

```dotenv
AUTH_SERVICE_INTERNAL_URL=https://auth-internal.example.invalid
AUTH_SERVICE_ID=cbs-backend
AUTH_SERVICE_CREDENTIAL=<service key provisioned in login-auth-service>
AUTH_APPLICATION_CODE=CBS
AUTH_SESSION_COOKIE_NAME=auth_session
AUTH_REQUEST_TIMEOUT=2.0
```

The service ID and 64-character lowercase hex credential must match a trusted
CBS-scoped entry in auth's `INTERNAL_SERVICES`. Use its **private listener**, port
8011, on the trusted Docker backend network. It has no host port by default;
`localhost:8010` is the public login API and does not expose internal resolution.
For trusted local HTTP only, explicitly set `AUTH_ALLOW_INSECURE_HTTP=true`.
Do not proxy `/internal/auth/resolve` to browsers or connect CBS to the auth DB.

For temporary diagnosis only, additionally set `APP_ENV=development` and
`AUTH_DEBUG_ENDPOINT_ENABLED=true`. `GET /dev/auth/whoami` then returns verified
`actor_id`, `application_code`, `actor_type`. It reads only the configured cookie;
request parameters cannot supply an identity. Use a cookie jar from the existing
login flow, with the same hostname for login and CBS:

```bash
curl -i -b cookies.txt http://localhost:8001/dev/auth/whoami
```

Missing/invalid sessions return 401, denied CBS access returns 403, and transport
failures or malformed upstream responses return 503. The current upstream
contract also reports invalid service credentials as 401. No retries, identity
cache or anonymous fallback are used. The client closes at app shutdown.
Diagnostics are disabled by default and cannot be enabled in production. Disable
or remove this temporary endpoint when finishing the authentication integration.

Phase 1 alone did not protect banking routes or create customer mappings.
Phase 2 below now introduces those identity links, `/me` and ADMIN route protection.

The Docker build needs an explicit named context for the independent package:

```bash
docker build --build-context auth_client=../../login-auth-service/packages/auth-client-python -t core-banking-system .
```

An opt-in real HTTP integration test is available as
`uv run --locked pytest tests/integration/test_auth_service.py -v`.
Point `CBS_AUTH_TEST_URL` at an isolated private auth listener and supply its
`CBS_AUTH_TEST_CREDENTIAL`, `CBS_AUTH_TEST_TOKEN`, `CBS_AUTH_TEST_ACTOR_ID` for a
CBS CUSTOMER session issued by that deployment. It checks verified identity and
rejection of unknown/missing sessions without writing to either database.
Absent configuration skips this test; use isolated test data rather than a real
customer's credentials or session.

## Auth integration — Phase 2: customer links and `/me`

The authoritative Customer records are in **CRP**, as explicitly selected for
this integration. CBS has no local Customer table and does not create one.
`banking.actor_customer_links` stores only `actor_id`, `customer_id`, `created_at`.
Actor IDs refer logically to auth; customer IDs refer logically to CRP. No
cross-database foreign keys are used. The actor is the primary key, while the
customer index is non-unique: several actors can share one Customer.

Apply the incremental migration with `make db-migrate`. No previous migrations
are rewritten and no customer or link is created automatically.

`GET /me` requires a verified CBS session. CUSTOMER responses return the persisted
customer UUID and `LINKED`, or `customer_id: null` and `PENDING_LINK` (HTTP 200).
ADMIN responses return `customer_id: null` and `NOT_APPLICABLE`. Lookup uses the
verified actor UUID only, never email, supplied customer IDs or demo selections.
It reads CBS persistence without contacting CRP on every request.

### Operator-only linking

Run the CLI on a trusted operator host with CBS PostgreSQL credentials. Database
and service credentials are the operational access boundary; do not distribute
them to customers or expose this command through an API. Link creation also
requires a valid session of the **target CBS CUSTOMER**, resolved through the
existing trusted auth integration. A mismatched actor, ADMIN, missing access,
expired/revoked session or unavailable auth service cannot be linked.

Configure the Phase 1 auth integration plus `PERSISTENCE_BACKEND=postgres`,
`DATABASE_URL` and `CRP_CUSTOMER_SERVICE_URL` (the CRP backend origin). The CLI
validates the exact customer UUID using CRP's existing `GET /customers/{id}`:
404 rejects creation; 200 must contain the matching UUID; network failures,
redirects, wrong IDs and malformed responses fail closed. CRP currently has no
service-authenticated customer lookup endpoint: use this read-only endpoint only
on a trusted private network or deployment boundary. No auth service credential
is forwarded to CRP and no CRP financial fields are persisted in CBS. For local
HTTP only, explicitly set `CRP_CUSTOMER_ALLOW_INSECURE_HTTP=true`.

```bash
# In the CBS repository; set real existing UUIDs, not demo defaults.
export ACTOR_ID='replace-with-existing-actor-uuid'
export CUSTOMER_ID='replace-with-existing-crp-customer-uuid'

# Securely prompts for the target Actor's current session token.
PYTHONPATH=src uv run --locked python -m link_customers link \
  --actor-id "$ACTOR_ID" --customer-id "$CUSTOMER_ID"

PYTHONPATH=src uv run --locked python -m link_customers show --actor-id "$ACTOR_ID"
PYTHONPATH=src uv run --locked python -m link_customers remove --actor-id "$ACTOR_ID"
```

For automation, `link --actor-session-env CBS_LINK_ACTOR_SESSION` reads the token
from a protected environment variable and removes that variable from the CLI
process environment. Do not pass the token itself in command arguments, commit
it, or include it in logs. Repeating `link` is rejected rather than reassigning
an Actor. Remove the previous link explicitly before an intentional reassignment.
`remove` is idempotent. Successful CLI output is emitted only after commit; a
failed operation rolls back the entire CBS transaction. Removing a link becomes
visible on the next `/me` request without changing the authentication session.

Customer existence is checked at linking time; CRP and CBS do not participate in
a distributed transaction. Later deletion or lifecycle changes in CRP need a
separate synchronization policy. No implicit customer or actor provisioning,
email matching or local Customer copies are introduced.

### Banking route protection (explicit scope extension)

All existing `/accounts` and `/transactions` routes, including balances and
movements, now require a verified **CBS ADMIN**. Anonymous users receive 401 and
CUSTOMER users receive 403 regardless of link state. Customer read endpoints are introduced in Phase 3 below; customer monetary
operation endpoints remain outside these phases. Missing or unavailable
auth configuration cannot grant access to banking routes.

Unsafe ADMIN browser requests also require an exact Origin in
`BANKING_TRUSTED_ORIGINS` and reject cross-site requests or browser fetch metadata
without Origin. For example, set
`BANKING_TRUSTED_ORIGINS=["http://localhost:5174"]` only if that is your trusted
local admin frontend origin. Non-browser CLI requests may omit Origin. The
frontend remains unchanged; opening the old admin interface without an ADMIN
session will therefore show authentication errors.

## Auth integration — Phase 3: customer read APIs

Linked CBS CUSTOMER sessions can now read their own banking data:

| Route | Response |
| --- | --- |
| `GET /me/accounts` | Own accounts, existing account pagination envelope |
| `GET /me/accounts/{id}` | Own account detail |
| `GET /me/accounts/{id}/balance` | Current balance projection |
| `GET /me/accounts/{id}/movements` | Own account movements, paginated |
| `GET /me/transactions` | Related transactions, paginated; optional `transaction_type` and `status` |
| `GET /me/transactions/{id}` | Customer transaction summary and paginated own movements |

All collection routes accept `limit` (1–100, default 50) and `offset` (>=0).
On transaction detail these parameters paginate the nested `movements` envelope,
which has the same `items`/`pagination` structure. Transaction lists order by
created time descending, then UUID ascending. Movements order by booking time
descending, then UUID ascending. Account lists retain UUID ordering.

`AccountAccessPolicy` derives the customer solely from the verified actor's CBS
mapping. An unlinked CUSTOMER receives 403 `Customer link required`; `/me` still
returns 200 with `PENDING_LINK`. ADMIN cannot use these CUSTOMER routes. Unknown
and other-customer accounts/transactions produce the same 404 response. Missing
sessions return 401 and auth outages fail closed with 503.

Account lists filter by customer in PostgreSQL before pagination. Transaction
lists use a movement/account subquery (a semijoin) so each transaction appears
once even if two of the customer's accounts participated. Totals and detail
movement pagination use the same customer filters.

Customer transaction responses deliberately omit idempotency keys, reversal
references and internal creation timestamps. Movement responses expose only
movement/transaction IDs, the customer's own account ID, direction, amount,
balance_after and booked_at. Counterparty fields and categories are omitted.
A transfer to another customer shows only the caller's movements and balance
snapshots. Current balances come from AccountBalance, without replaying history.

Read responses use `Cache-Control: no-store`. No new write routes, frontend
changes or migrations are introduced in this phase. Existing administrative
routes continue to require ADMIN. Link removal is checked on subsequent requests;
no customer identity is cached across requests.

## Auth integration — Phase 4: authorized customer transfers

| Endpoint group | Access |
| --- | --- |
| Existing `/accounts` and `/transactions`, including mutations, balances and movements | CBS ADMIN |
| `/me/accounts...` and `/me/transactions...` reads | Linked CBS CUSTOMER; ownership enforced |
| `POST /me/transfers` | Linked CBS CUSTOMER; source owned by caller |
| `GET /me` | Verified CBS identity |
| `/dev/auth/whoami` | Verified CBS identity; opt-in development diagnostics |
| Health and API documentation | Public |

No seed endpoints or unprotected banking aliases are registered. Existing
administrative URLs remain intact. Customer deposits and withdrawals do not exist.
Customer transfers use the existing TransferRequest and Idempotency-Key contract,
and return the customer-safe transaction summary without destination balances,
movements, idempotency receipts or private counterparty information.

`CreateCustomerTransfer` delegates to `CreateTransfer`. The existing posting
coordinator has one optional authorization hook immediately after the idempotency
lock and before receipt lookup. For CUSTOMER calls it locks the actor/customer
link, verifies source ownership, locks account rows in UUID order, and checks
ownership again against current locked data. The same transaction retains those
locks through posting/commit. Existing funds, status, currency, balance locking,
movement snapshots and idempotency logic remain in the existing posting flow.
Authorization is checked again even on retries, before returning a prior result.
All banking browser writes use the trusted-origin protection described above.

## Auth integration — Phase 5: authenticated banking frontend

The existing CBS UI now restores `/auth/me` and CBS `/api/me`. ADMIN enters the
existing Administration pages; CUSTOMER enters `/me`; missing CBS access shows
Access Denied. Unlinked CUSTOMER profiles show only the pending-link state.
The demo selector and customer deposits/withdrawals are removed from customer
banking. Existing account cards, money, balance, movement, transaction and
operation components are reused without a UI framework change.

Customer data uses only `/api/me/...`; transfer destination entry is a UUID,
matching the existing backend contract. It does not query another customer's
account via administrative lookup. Currency/state validation remains server-side.
The transfer form preserves confirmation and one stable idempotency key per
intent, including uncertain retries. Source selection uses own active accounts.

Private query clients are isolated per restored session. Confirmed logout or 401
unmounts private content, cancels/clears queries and removes pending operation
state. A late monetary response cannot repopulate the active session's cache or
storage. Logout failures do not claim revocation. 403 and 503 are not treated as
expired sessions. No session tokens are read by JavaScript, stored locally or
included in URLs; requests use the issuer's HttpOnly cookie.

### Authentication routing

The banking origin routes `/auth/*`, `/login`, `/register`, and `/assets/auth/*`
to the public authentication service, and `/api/*` to CBS with the prefix removed.
The fixed login success path `/account` returns to the SPA, which verifies both
`/auth/me` and `/me` before selecting the ADMIN or CUSTOMER workspace.
The private session-resolution listener is never a browser proxy target.
Use HttpOnly cookies, a consistent browser origin, explicit trusted origins and
HTTPS/Secure cookies in deployments. Backend service credentials must never be
included in frontend variables. Vite's proxy is only a development adapter;
deployment routing belongs to a trusted reverse proxy.

## Customer onboarding after login

An unlinked CUSTOMER now sees a CBS profile form after login. It collects the
actual CRP CustomerCreate fields (birth date, employment, income/expenses,
housing and country) plus the desired savings-account currency. No income,
customer identity or other profile data is invented.

`POST /me/onboarding` derives actor_id from the verified session, accepts no
actor/customer IDs or email, and orchestrates:

1. Persist one server-generated Customer UUID and a profile fingerprint per Actor
   in `banking.customer_onboardings` before contacting CRP.
2. Call CRP's private, service-authenticated
   `PUT /internal/customer-provisioning/{customer_id}` with that stable UUID.
   CRP creates once, returns the same Customer for identical retries, and rejects
   attempts to overwrite an existing profile with different data.
3. In one CBS transaction, create the Actor-Customer link, savings account and
   zero opening balance, then mark the workflow complete. Repeated and concurrent
   requests return the same account. Existing manually linked Actors are not
   silently reassigned. Unlinking a completed Actor does not permit the workflow
   to reveal or automatically re-link the previous account.

The relationship is `Actor.id → actor_customer_links.customer_id → Account.customer_id`.
The authoritative Customer stays in CRP; auth stores only login identity and CBS
access. Email is never used to guess or merge banking identities.

Only UUIDs, a fingerprint and the completed account ID are stored in the CBS
workflow record; the full financial profile is not duplicated there. An uncertain
network result retains the original request in the form for retry. On a page
reload, re-enter the same profile to resume a pending workflow. Changed data for
an existing request returns 409 rather than creating another Customer. Explicit
CRP validation rejection allows correction. A CRP Customer can remain created
while CBS is unavailable; retry completes the local transaction using the same
UUID. There is no distributed transaction and no automatic deletion in CRP.

### Onboarding service boundary

Both CBS and CRP use PostgreSQL. Configure `CRP_CUSTOMER_SERVICE_URL` and the
matching server-side provisioning credentials through protected environment
configuration. The CRP provisioning route is enabled only when its credential
is configured; it rejects browser-originated traffic and is never a frontend
proxy target. Restrict internal traffic to trusted networks and use HTTPS across
untrusted networks. Account opening finishes by refreshing `/me` and displaying
the new savings account with a zero opening balance. Deposits remain ADMIN-only.

## Coordinated registration from login-auth-service

New registrations submit one complete form to auth. Credentials stay in auth; the Customer
profile is transient there and is stored only in CRP. Auth reserves an inactive Actor and
calls CBS on its **separate private listener**, authenticating with the dedicated
REGISTRATION_SERVICE_CREDENTIAL and X-Service-ID=auth-registration. CBS reuses
OnboardCustomer, CRP idempotent creation, and the atomic link/account/zero-balance write.
Actor UUID identifies the stable CBS workflow; the browser cannot choose actor/customer
IDs. Successful linkage is confirmed before auth activates the Actor. Existing links,
Customers, Accounts, transactions and fallback onboarding for older unlinked Actors remain.
The current Customer model has no first_name/last_name/gender/financial_currency; the form
uses actual required business fields and the existing optional employment_months.

Run registration on the separate `api.internal:app` listener, restricted to
trusted backend services. The public app does not mount internal routes, and
the private app exposes neither public banking routes nor OpenAPI. Requests
require a dedicated registration credential and reject browser Origin/Sec-Fetch
headers. Private `PUT /internal/registrations/{actor_id}` accepts OnboardingRequest
and returns actor_id/customer_id/status=LINKED. `GET` at the same path confirms
an existing completed account and matching link for operator recovery.
Use separate keys for registration, session resolution and CRP provisioning.
Keep keys server-side and rotate the corresponding services together.

No cross-database transaction is assumed. A failure preserves the stable Customer UUID;
repeating the original request recovers it without duplicating data. Auth keeps its Actor
inactive until confirmed; incomplete users cannot obtain a valid session or bank access.
An operator can reconcile a lost success response using auth_service.reconcile_registration;
there is no public self-service linking, email matching or automatic Customer deletion.
No development databases are reset or backfilled by the new auth migration.

Validation: make check; PostgreSQL integration tests include private-route isolation,
credentials, browser rejection, idempotent provisioning, and uncertain-result recovery.
`tests/integration/test_registration_workflow_http.py` is opt-in using
REGISTRATION_AUTH_TEST_URL, REGISTRATION_CBS_TEST_URL, REGISTRATION_CRP_TEST_URL, each an
isolated loopback test service backed by temporary *_test databases. It checks full form
registration → login → /auth/me → /me LINKED → own account/zero balance → logout.
