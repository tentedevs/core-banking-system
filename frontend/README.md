# CBS frontend

Independent React/TypeScript/Vite interface for CBS Accounts. All source,
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
make db-init
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
Balances, credit evaluations, customer synchronization and ledger are not part
of CBS's current Accounts API and are not displayed.

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
