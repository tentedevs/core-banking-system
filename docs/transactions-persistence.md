# Transactions persistence — Phase 2

TransactionORM and AccountMovementORM are registered on the existing Base in
`infrastructure/persistence/models.py`. No new engine, session factory, repository
or application transaction boundary is introduced. The domain remains unchanged
and independent of persistence.

Revision `0002_create_transactions` follows `0001_create_accounts`, reuses the
banking schema and creates:

- `banking.transactions`: UUID identity; VARCHAR type/status; NUMERIC(18,2)
  amount; CHAR(3) currency; nullable text description; timezone-aware effective,
  posting and creation timestamps; unique nullable VARCHAR(100) idempotency key;
  and nullable self-referencing reversal UUID.
- `banking.account_movements`: UUID identity and transaction/account FKs;
  VARCHAR direction; NUMERIC(18,2) amount and nullable balance_after; nullable
  category/counterparty strings with the specified lengths; and TIMESTAMPTZ
  booked_at. Negative historical balance_after remains permitted.

Enums use VARCHAR with named checks, as in Accounts, without PostgreSQL native
enum types. Transaction status defaults to PENDING at the server. Checks enforce
valid types, statuses and directions, positive finite amounts, normalized
currency format, finite historical balances, status/posting-time consistency,
and no self-reversal. NaN is explicitly excluded: PostgreSQL NUMERIC otherwise
allows it and treats it as greater than finite numbers. Unknown statuses are
rejected by the status check independently of posting-time validation.

The transaction index is `(status, created_at DESC)`. Movement indexes cover
`(account_id, booked_at DESC, id)` and transaction_id. FKs prevent references to
missing transactions/accounts and prevent deletion of referenced rows; no
cascade deletion behavior is introduced. Multiple NULL idempotency keys are
allowed, while duplicate non-NULL keys are rejected by PostgreSQL.

## Mapping and precision

`transaction_mapper.py` and `account_movement_mapper.py` provide to_orm/to_domain
functions following Accounts. They preserve identifiers, enum values, Decimal
values, nullable metadata, status and reversal links. Reconstruction calls the
validated domain constructors, never creation factories. Missing or expired ORM
fields are rejected before implicit SQL can execute. Timestamps must be aware
in both mapping directions. PostgreSQL preserves the represented instant, not
the original timezone offset.

The Phase 1 domain accepts arbitrary finite Decimal precision. The requested
NUMERIC(18,2) schema supports 16 integer digits and 2 fractional digits, with a
maximum magnitude of 9999999999999999.99. Mappers reject out-of-range or non-cent
values before persistence rather than silently rounding. Exact values with
additional trailing zeroes, such as 1.2300, remain accepted without mutating the
domain Decimal. Validation does not depend on the active Decimal context.
PostgreSQL returns persisted values at scale 2. Direct SQL bypasses these mapper
guards and follows PostgreSQL's native NUMERIC coercion rules.

## Migration and verification

Upgrade creates only the two new tables, their checks, FKs, uniqueness constraint
and indexes. Downgrade removes movements before transactions and retains Accounts
and the shared schema. The existing Accounts migration is unchanged.

Apply explicitly with `make db-migrate` against the intended configured database.
The Phase 2 validation uses a disposable PostgreSQL 16 service and the existing
per-test isolated databases. It verifies metadata parity, numeric types and
descending indexes, mapper/database round-trips, all types and statuses, FK/check
failures through raw SQL, idempotency uniqueness, NULLs, negative historical
balances, and upgrade/downgrade/re-upgrade with an existing account preserved.

No account balances, ledger, posting execution, repositories, use cases, API
routes, frontend, seeds or source-specific adapters are added. Cross-row posting
cardinality and parent-status rules remain responsibilities of future application
coordination; these tables do not implement those workflows.
