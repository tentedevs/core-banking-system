# CBS frontend

Independent React/TypeScript/Vite interface for CBS Accounts and Transactions. All source,
dependencies and lockfiles live in this repository; CRP is not a runtime
dependency. Requires Node 22.12+; the root `.nvmrc` selects the installed Node 22
version used for verification.

From the CBS project root:

```sh
nvm use
make frontend-install
make frontend-dev
```

Open **http://127.0.0.1:5174**. The frontend development proxy sends `/api/*`
to **http://127.0.0.1:8001**, removing `/api`. There is no dependency on ports
5173 or 8000. To override the backend address, copy `frontend/.env.example` to
`frontend/.env` and adjust API_PROXY_TARGET. No credentials belong in frontend
environment variables.

Run CBS's backend in another terminal:

```sh
make db-up
make db-migrate
PERSISTENCE_BACKEND=postgres make dev
```

The interface supports:

- A paginated account directory with totals and customer UUID filtering.
- Lookup by UUID or exact account number, preserving leading zeros and formatting.
- New savings accounts, supplying only customer UUID and currency (default CZK).
- Account details with all returned dates, reference fields, currency and status.
- ACTIVE → BLOCKED and BLOCKED → ACTIVE using the backend's responses.
- Read-only CLOSED accounts, request progress, HTTP errors and 409 state refresh.

There are no production fixtures or mock results. Account numbers and identity
are assigned by CBS. Customer existence is not yet checked by the backend.
Currency must be three uppercase letters; registry membership is not verified.
Account detail also displays the live balance projection and paginated movements,
with links to their transactions and preselected deposit/withdrawal/transfer actions.
Components for balance, monetary display, movements and pagination are shared.

## Transactions

- /transactions: real server-side type/status filters, pagination, refresh, and
  loading/empty/error states. No synthetic KPI data.
- /transactions/:transactionId: financial snapshot plus paginated associated
  movements, including both sides of an internal transfer and empty histories.
- /transactions/new/deposit, /withdrawal and /transfer: paginated active-account
  selection, exact decimal strings, matching account currency and explicit review
  followed by confirmation. The full paths for the latter two also start with
  /transactions/new. An optional ?account=UUID preselects the source account.
- Successful operations invalidate affected balances/movements and transaction
  queries; displayed balances always come from the backend. No optimistic balance
  arithmetic, floats or locally calculated available funds are used.

The existing API lacked a transaction-scoped movement lookup. This phase adds
only GET /transactions/{transaction_id}/movements to the backend, using existing
mappers, repositories, Unit of Work, pagination and 404 behavior. It reads known
transactions with no movements as an empty page. There are no schema migrations
or changes to monetary posting. See ../docs/transactions-api.md.

## Idempotency and uncertain outcomes

One cryptographic UUID key is generated when an intentional operation is reviewed.
The frozen payload and key are saved in sessionStorage before submission; the UI
cannot submit if this save fails. Confirmation is explicit, duplicate button
submissions are blocked, and React Query monetary retries are disabled.

Network failures, 5xx responses and incomplete/mismatched success bodies leave the
request uncertain. The form offers only an explicit retry with the same payload
and key. Reloading or navigating between operation forms restores the saved
request, rather than creating another intent. Another operation cannot replace an
uncertain one. A valid confirmed POSTED response clears the draft and opens the
transaction detail. A definite business failure can be explicitly retried with
its original key or replaced by a deliberately new operation. Keys are not rotated
as a response to network errors or idempotency conflicts.

Session storage is scoped to this browser tab/origin and is not a durable operation
queue. Closing the tab or clearing browser data loses local recovery information;
check backend transaction history before replacing any operation whose outcome was
uncertain. The backend remains the durable source of truth. The transaction detail
shows the request reference to support inspection. This is an internal local
console: there are no authentication, authorization or access-control guarantees.
No ledger, external payments or simulation engine is implemented.

```sh
make frontend-typecheck
make frontend-lint
make frontend-test
make frontend-build
```

Frontend tests use test-only HTTP fixtures and the real client, routes and React
Query lifecycle. Production output is in frontend/dist. Deployment needs a
server with SPA fallback and an `/api` reverse proxy to CBS; this change prepares
and verifies local development and the build, without publishing a deployment.
