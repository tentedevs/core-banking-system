# Transactions REST API — Phase 6

The monetary and read operations are registered in the existing FastAPI app under the
Transactions tag. Interactive documentation: http://127.0.0.1:8001/docs.
OpenAPI: /openapi.json. Accounts retains the SAVINGS_ACCOUNT spelling.

| Method | Path | Success | Behavior |
| --- | --- | --- | --- |
| POST | /transactions/deposits | 201 | Simulated cash inflow, one CREDIT |
| POST | /transactions/withdrawals | 201 | Cash withdrawal, one DEBIT |
| POST | /transactions/transfers | 201 | Internal transfer, DEBIT + CREDIT |
| GET | /transactions | 200 | Paginated transactions, type/status filters |
| GET | /transactions/{transaction_id} | 200 | Transaction snapshot |
| GET | /transactions/{transaction_id}/movements | 200 | Paginated associated movements (frontend Phase 2) |
| GET | /accounts/{account_id}/movements | 200 | Paginated account movements |
| GET | /accounts/{account_id}/balance | 200 | Current balance projection |

## Request and response contracts

Writes require an Idempotency-Key header: a stable, nonblank string of at most
100 characters, compared exactly. Reuse it for retries after timeouts; change it
for a genuinely new operation. An identical request returns the original body
and 201, with no new monetary effects or additional commit. Reusing a key with
a different type, participating account/role, amount, currency or description
returns 409. Equivalent Decimal scales are equivalent; absent/null descriptions
are equivalent, while an empty string is distinct from null. PostgreSQL advisory
locks, receipt fingerprints and uniqueness constraints protect concurrent retries.

Deposit/withdrawal JSON has account_id, amount, currency, and optional description
(default null). Transfer JSON replaces account_id with source_account_id and
destination_account_id; they must differ. UUIDs are parsed and validated.
Amounts must be JSON strings containing positive, finite Decimal values that fit
NUMERIC(18,2), without rounding. JSON numeric amounts are rejected to avoid float
precision loss. Currency is exactly three uppercase ASCII letters and must match
all participating accounts. ISO membership is not verified. Extra fields,
including status, balance_after and body idempotency_key, return 422.

Responses serialize money as strings with two decimal places, enum values as
strings, UUIDs as strings and timestamps as timezone-aware ISO 8601 strings.
Transaction responses contain all BankingTransaction fields, including status,
posted_at and reversal_of_id. Read statuses include PENDING, POSTED, REJECTED and
REVERSED; successful live writes return POSTED. Reversal execution is unavailable.
Movements include transaction/account references, direction, amount, balance_after,
category, optional counterparty metadata and booked_at. balance_after is the
historical snapshot at booking, not the current balance.

Balance responses contain account_id, booked_balance, available_balance and
updated_at. The endpoint reads the projection directly; it does not recalculate
history. Available and booked balances currently match because reservations are
not implemented. Historical negative projections may exist; live operations
cannot create an overdraft. Existing accounts without an initialized balance
return 409; reads never initialize or backfill a projection. New POST /accounts
operations initialize their projection atomically.

## Atomicity and pagination

The routes invoke the existing application use cases and contain no commits,
balance calculations or SQLAlchemy imports. A request receives its own existing
Unit of Work with a shared Session across repositories. Accounts and balances
are locked in deterministic UUID order; account status remains protected against
concurrent blocking through commit. Transaction, movement(s), projection updates
and idempotency receipt commit together. Failure rolls everything back. A rejected
operation does not persist a separate REJECTED record.

GET /transactions accepts transaction_type (DEPOSIT, WITHDRAWAL, TRANSFER),
status (PENDING, POSTED, REJECTED, REVERSED), limit (1..100, default 50) and offset
(nonnegative, default 0). It orders by created_at DESC, id ASC. Account movements
accept the same pagination arguments and order by booked_at DESC, id ASC.
Pagination is performed by PostgreSQL. The envelope matches Accounts:

```json
{
  "items": [],
  "pagination": {"limit": 50, "offset": 0, "total_items": 0, "total_pages": 0}
}
```

Totals count all matching rows before pagination, including when offset is past
the last result. Reads do not commit. As with Accounts, list and count use separate
statements in one READ COMMITTED context; totals can change during concurrent
writes. UUID tie-breaks give deterministic ordering for equal timestamps.

## Errors

All responses use the existing detail envelope; validation errors can contain
structured Pydantic details.

| Status | Condition |
| --- | --- |
| 404 | Unknown account or transaction |
| 409 | Insufficient funds, non-ACTIVE account, idempotency conflict, uninitialized balance |
| 422 | Invalid request/header/UUID/amount/pagination/filter, same-account transfer, incompatible currency |
| 500 | Unexpected internal failure, with a generic response |
| 503 | Persistence unavailable, following existing Accounts error handling |

Database errors never expose SQL, credentials or stack traces in responses.
A timeout or connection failure can leave the client uncertain whether commit
completed: retry the identical request with its original key.

## Local smoke test

From the project root, with Docker running and DATABASE_URL configured:

```sh
make db-up
make db-check
make db-migrate
PERSISTENCE_BACKEND=postgres make dev
```

In another terminal, create an account. Its response supplies the UUID to use
in the next commands. Use a new account if historical accounts have no projection.

```sh
curl -i -X POST http://127.0.0.1:8001/accounts \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"a2b6c4d8-9241-4d16-bfe2-2c66e17a0001","currency":"CZK"}'
```

Set the returned account UUID, then deposit and inspect the projection:

```sh
ACCOUNT_ID='REPLACE_WITH_RETURNED_ACCOUNT_UUID'

curl -i -X POST http://127.0.0.1:8001/transactions/deposits \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: manual-deposit-001' \
  -d "{\"account_id\":\"${ACCOUNT_ID}\",\"amount\":\"500.00\",\"currency\":\"CZK\",\"description\":\"Deposit\"}"

curl -sS "http://127.0.0.1:8001/accounts/${ACCOUNT_ID}/balance"
curl -sS "http://127.0.0.1:8001/accounts/${ACCOUNT_ID}/movements?limit=10&offset=0"
curl -sS 'http://127.0.0.1:8001/transactions?transaction_type=DEPOSIT&status=POSTED&limit=10'
```

Repeat the identical deposit to verify the transaction ID and 500.00 balance
are unchanged. For a withdrawal use /transactions/withdrawals with the same body
shape and a fresh key. For a transfer, create a second account and send source and
destination UUIDs to /transactions/transfers with a fresh key.

## Validation and boundaries

Run make check, then make test-integration with TEST_DATABASE_URL pointing to a
dedicated database ending in _test. Fixtures migrate and drop a unique database
per test; the development database is untouched. Unit API tests override the
existing UOW dependency, while integration API tests use the real dependency
chain, repositories, PostgreSQL and transaction boundaries.

No ledger, accounting journal, frontend, external payment, replay, importer,
interest engine or simulation agent is implemented. Deposits are explicitly
simulated cash inflows, not transfers from an unidentified CBS account.


Frontend Phase 2 adds GET /transactions/{transaction_id}/movements. It accepts the
same limit/offset bounds and movement envelope as account movements, orders by
booked_at DESC then UUID ASC, and returns 404 for an unknown parent transaction.
A known PENDING/REJECTED transaction without movements returns an empty page.
Both transfer sides are available without scanning accounts. This is a read-only
extension with no migrations or monetary workflow changes.
