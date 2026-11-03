# Monetary application operations (no ledger)

CreateDeposit, CreateWithdrawal and CreateTransfer accept immutable commands from
application.transaction_messages. Amounts must be positive finite Decimal values,
exactly representable by NUMERIC(18,2). Currency uses the existing uppercase
three-letter Accounts contract; ISO membership is not verified. Every write
requires a nonblank idempotency key of at most 100 characters. SAVINGS_ACCOUNT
remains the supported account product.

All three use the existing AccountUnitOfWork, extended with transactions and
movements repositories on the same Session as accounts and balances. The name
is retained for compatibility. Repositories flush but never commit, roll back,
close the session or open another session. Only the write use case commits.

## Posting and locking

The application obtains a PostgreSQL transaction-scoped advisory lock for the
idempotency key, then locks the complete participating account/balance set in
ascending UUID order through AccountBalanceService. Account row locks protect
ACTIVE status against concurrent blocking. All locks remain held until commit
or rollback. Internal transfers prelock both accounts before changing either.

A new PENDING transaction is inserted, the projection is updated, and the exact
movement set is appended: deposit one CREDIT, withdrawal one DEBIT, transfer one
of each. Each movement records its updated balance_after, parent transaction and
common booking/posting timestamp. Transfers record the other CBS account number
as counterparty. Only then is the transaction marked POSTED and the idempotency
receipt stored. A single commit makes all effects visible together. Failure at
any point discards every write, including key reservation. Insufficient funds
raises InsufficientFunds; this implementation does not separately persist a
REJECTED record. Historical negative projections cannot be further overdrawn or
left negative by live credit operations.

Deposits have category SIMULATED_CASH_DEPOSIT: explicitly simulated external cash
inflows, with no invented source CBS account. Withdrawals use CASH_WITHDRAWAL;
transfers use INTERNAL_TRANSFER. These are operational movements, not accounting
entries. There is no external settlement, external transfer, FX or ledger.

## Durable idempotency

Migration 0004_create_transaction_requests adds an immutable receipt table with
key, SHA-256 request fingerprint and unique transaction reference. Existing
migrations and historical transactions are preserved. The canonical version-1
fingerprint contains operation type, ordered source/destination roles or account,
exact two-decimal amount, currency and description. Equivalent Decimal scales
produce the same fingerprint; None and an empty description remain distinct.
The key is compared exactly, without trimming or case conversion.

The transaction-scoped advisory lock is derived deterministically from SHA-256
of the key. It serializes even requests whose receipt does not exist yet.
Hash collisions merely serialize unrelated keys; actual identity and conflict
checks still use the full database key and request fingerprint. At the existing
READ COMMITTED isolation level, the next query after acquiring the lock sees the
previous request's committed receipt. Duplicate identical requests return the
original persisted BankingTransaction without another monetary commit, even
when the account was subsequently blocked. A different fingerprint raises
IdempotencyConflict before account changes. PostgreSQL uniqueness constraints
provide a final backstop; known key violations are translated at the existing
Unit of Work boundary, while unrelated database errors propagate.

An old transaction key without a verifiable receipt raises IdempotencyConflict;
we never guess its original request or execute it again. Downgrading 0004 deletes
receipts while retaining financial history and transaction keys; after reupgrade
those keys require manual investigation rather than automatic replay. Do not
prune receipts or transaction keys while clients may retry. Callers must use a
fresh Unit of Work per execution and avoid wrapping multiple write use cases in
another context: each use case owns its one atomic operation. These guarantees
assume all monetary writers use this application locking protocol; direct SQL
can bypass it.

## Reads and reconciliation

GetTransaction returns an immutable domain transaction or TransactionNotFound.
ListTransactions filters type/status in PostgreSQL and orders by created_at DESC,
id ASC. ListAccountMovements verifies the account exists and orders its movements
by booked_at DESC, id ASC. Both lists use limit 1..100 and nonnegative offset.
GetAccountBalance returns the existing projection; it never initializes one.
Missing accounts raise AccountNotFound, and missing projections BalanceNotFound.
Reads exit without a commit. No SQLAlchemy types enter application contracts.

AccountBalanceService.check_consistency compares the explicit opening plus signed
posted movements with the projection. Successful operations preserve that relation
for initially consistent accounts. This phase does not repair pre-existing
projection discrepancies or provide replay/reversal execution.

## Running and validating

Apply `make db-migrate` explicitly before using these application operations on
a development database; startup does not migrate automatically. No development
database is changed by the tests. Use `make check` for lint, formatting, types and
unit tests. PostgreSQL integration tests run with TEST_DATABASE_URL pointing to a
dedicated database ending in _test; fixtures create and drop a unique database
per test. See tests/integration/README.md.

Phase 6 exposes the application layer through the [Transactions REST API](transactions-api.md). There are no Transactions frontend components.
