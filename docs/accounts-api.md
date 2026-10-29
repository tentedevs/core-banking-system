# Accounts REST API — Phase 5

Accounts uses the existing FastAPI application without a global URL prefix.
Interactive documentation is at `/docs`, with the six operations grouped under
the `Accounts` tag. The supported product remains `SAVINGS_ACCOUNT`, as confirmed
in Phase 4; the old `SAVING_ACCOUNT` spelling is not introduced.

| Method | Path | Success | Purpose |
| --- | --- | --- | --- |
| POST | /accounts | 201 | Create an ACTIVE savings account |
| GET | /accounts | 200 | List accounts, optionally filtered by customer |
| GET | /accounts/{account_id} | 200 | Retrieve by UUID |
| GET | /accounts/by-number/{account_number} | 200 | Retrieve by exact number |
| PATCH | /accounts/{account_id}/block | 200 | ACTIVE → BLOCKED |
| PATCH | /accounts/{account_id}/reactivate | 200 | BLOCKED → ACTIVE |

The by-number route is registered before the UUID route. Numbers are preserved
without stripping, case conversion or reformatting. Historical CLOSED accounts
are readable but cannot be blocked or reactivated. There is no closure endpoint.

Creation accepts only `customer_id` (UUID) and optional `currency` (default CZK).
Extra fields, including ID, account number, product and status, are rejected.
The domain validates currency as three uppercase ASCII letters; ISO membership
is not yet verified. The application/domain generates UUIDs, internal account
numbers, status and timestamps. These numbers are internal references, not IBANs.
Customer existence is **not verified** in CRP or another service. As in CRP's
creation endpoints, the response contains the created entity without a Location
header.

Responses contain all ten Account fields: UUIDs and enum values as strings,
ISO 8601 dates, timezone-aware ISO 8601 datetimes, and null for an absent closing
date. Pydantic response validation requires aware audit timestamps. The response
schema reads domain attributes; it never serializes ORM objects.

## Pagination

GET /accounts accepts `customer_id` (optional UUID), `limit` (1–100, default 50),
and `offset` (>= 0, default 0). UUID ascending ordering is deterministic. The
response follows CRP's `items` and `pagination` envelope, adapted to the requested
offset/limit interface instead of CRP's page/page_size inputs:

```json
{
  "items": [],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total_items": 0,
    "total_pages": 0
  }
}
```

`total_items` counts all matching accounts before pagination, and `total_pages`
is its ceiling divided by limit. An offset beyond the end returns empty items
while preserving the matching total. The repository port gains `count` with an
optional customer filter. ListAccounts.execute_with_total performs the bounded
list and COUNT through the repository in one Unit of Work context. The existing
execute method retains its list return type. No rows are paginated in Python.

## Dependencies and errors

API dependency functions construct a request-local Unit of Work from the existing
application session factory and inject the six existing use cases. They open no
Session themselves. The use case's context manages the Session and its write
commit, rollback and close before returning. Accounts does not use the older
request-level SessionDependency, avoiding duplicate transaction boundaries.
Repositories and routes never call commit. Reads never commit. Number generation
is separately injectable for testing.

The default `PERSISTENCE_BACKEND=memory` still disables persistence; there is no
production in-memory Account store. Accounts then returns 503, while health and
OpenAPI remain available. For persisted operation, explicitly apply migrations
and start with `PERSISTENCE_BACKEND=postgres` as described in the root README.

Global handlers preserve the `detail` error envelope:

| Failure | Status |
| --- | --- |
| AccountNotFound | 404 |
| InvalidAccountStateTransition | 409 |
| AccountNumberConflict | 409 |
| HTTP validation or InvalidAccountData | 422 |
| Disabled persistence or SQLAlchemy error | 503, following existing CBS/CRP behavior |
| Unexpected application error | 500 |

FastAPI validation errors retain their structured detail list; other errors use
a detail string. Only the specifically identified account-number constraint
conflict maps to 409. SQLAlchemy responses remain generic and redact SQL and
credentials; unexpected errors also receive a generic response and are logged
through the existing Uvicorn logger. Business exceptions never import HTTP types.

## Verification and scope

Unit HTTP tests override the Unit of Work or individual use cases and exercise
input/output schemas, routing, pagination/counts, errors and OpenAPI. Real
PostgreSQL HTTP tests verify committed creation, both lookup routes, filtered
lists and totals, persisted blocking/reactivation, duplicate-number rollback,
no read commits and session release. Existing lower-layer suites remain green.

CRP is unchanged. No frontend, seed data, customer synchronization, balances,
transactions, ledger, interest features or extra products are added. No new
migration is required. Phase 6 is not started.
