# Account balances without ledger — Transactions Phase 4

This phase adds an internal balance projection; it does not add financial
transaction execution, deposit/withdrawal/transfer endpoints, or a ledger.
The current repository has Transactions entities, ORM models and mappers but
does not yet have Transactions/Movements repository ports. The balance work
reuses their tables directly through its own infrastructure query, without
introducing those missing repositories or changing their domain.

## Projection and opening metadata

AccountBalance is a separate frozen domain entity containing account_id,
booked_balance, available_balance and updated_at. Amounts must be finite Decimals
and available_balance equals booked_balance in this MVP. Controlled credit and
debit methods return new snapshots. Ordinary debits require sufficient funds;
ordinary operations cannot leave negative balances. Decimal arithmetic preserves
precision independently of the caller's Decimal precision setting. Storage
mappers enforce the existing NUMERIC(18,2) range/scale and aware timestamps.

New balances default to zero. Nonzero initialization is an explicit internal
operation. Negative openings require BalanceInitializationPolicy.HISTORICAL;
ordinary initialization rejects them. A historical negative snapshot can be
represented, read and reconciled. Subsequent ordinary debits remain prohibited,
and an ordinary credit must cover the historical negative amount sufficiently
to produce a non-negative balance. There is no public historical initialization
API or importer.

Revision `0003_create_account_balances` creates banking.account_balances with a
primary/foreign account UUID key, NUMERIC(18,2) balances and TIMESTAMPTZ updated_at.
Checks enforce finite values and equal booked/available balances. Negative values
cannot be universally prohibited at the table level because historical snapshots
are explicitly supported; ordinary operation limits belong to the domain/service.

The revision also creates banking.account_balance_openings: one immutable logical
opening record per balance, containing opening_balance, initialization policy
and initialized_at. This small metadata table is necessary to retain an explicit
reconciliation baseline without adding balance fields to Account or disguising
an opening as a deposit. It is not a journal or a ledger. Repository APIs expose
no update or reset operation for openings. Its FK requires an existing balance;
checks enforce finite values and explicit historical policy for negative openings.
Neither earlier migration is changed. Downgrade removes these two tables only.

## Repository, service and transaction ownership

The BalanceRepository Protocol is in ports/. Its SQLAlchemy adapter receives the
existing Session. AccountUnitOfWork exposes accounts and balances repositories
sharing that same Session, and retains ownership of commit/rollback/close.

Repository methods provide ordinary reads, explicit initialization, SELECT FOR
UPDATE reads and persistence of updated snapshots. Writes require a lock acquired
in the same active transaction/savepoint context; cached lock evidence cannot
be reused after commit. Locked reads refresh previously loaded ORM identities.
Initialization uses explicit insert/flush, never merge/upsert, and duplicate
primary keys raise BalanceAlreadyInitialized. Flush is used to surface errors
inside the caller's transaction; repositories and balance service never commit,
rollback, close or create an independent Session.

AccountBalanceService accepts those two injected ports and provides initialize,
credit, debit, lock_accounts and check_consistency. Currency is a required keyword
and must match the associated Account. It takes the Account row lock first,
then the balance lock. lock_accounts sorts unique UUIDs deterministically. Any
future multi-account operation must acquire the full account set through this
method before performing changes; repeated single-account calls in arbitrary
order are not a substitute for that protocol. Exceptions must propagate out of
the caller's Unit of Work context for rollback of the whole operation.

CreateAccount now saves Account, initializes its zero balance and opening record,
and commits once through the existing Unit of Work. Any failure rolls all three
inserts back. Its API request/response schema and frontend are unchanged.

## Existing accounts and explicit backfill

Run `make db-migrate` before using the updated backend. The migration does not
guess balances or silently create zero projections for existing accounts. Such
accounts remain readable through Accounts; internal monetary operations raise
BalanceNotFound until initialization has been explicitly completed.

An operator can identify missing projections with a read-only query:

```sql
SELECT a.id, a.currency
FROM banking.accounts AS a
LEFT JOIN banking.account_balances AS b ON b.account_id = a.id
WHERE b.account_id IS NULL;
```

For an account with a known authoritative opening balance and no posted movements,
an internal controlled process can call AccountBalanceService.initialize inside
the existing Unit of Work, supplying currency and the explicit opening value.
Use HISTORICAL policy for an authorized negative historical opening. Commit only
after successful initialization. An existing projection always causes an error;
there is no overwrite/reset behavior.

If POSTED or REVERSED movements already exist, initialization raises
BalanceInitializationRequiresReplay even when their net sum is zero. Treating a
known current balance as an opening would double-count those movements. A separate
controlled reconstruction procedure will be required; this phase does not provide
that replay or calculate opening balances from Berka or other datasets.

## Consistency preparation and limitations

check_consistency obtains account/balance locks and evaluates:

`opening_balance + sum(posted signed movements) == booked_balance`

CREDIT contributes positively and DEBIT negatively. Only movements whose parent
transaction is POSTED or REVERSED with posted_at present are included; original
posted effects remain part of the audit trail after reversal, alongside any
separate compensating transaction. PENDING/REJECTED movements are excluded.
A missing opening raises an explicit error rather than assuming zero. A posted
movement in another currency also raises an error instead of combining currencies.
The result includes opening, signed total, current booked balance and consistency.

Credit/debit only coordinate the projection: they do not create BankingTransaction
or AccountMovement records. A future transaction executor must write those audit records and the projection
within the same Unit of Work. A projection change
without corresponding posted movements is intentionally reported as inconsistent.
All future writers must follow the same account locking protocol; raw SQL can
bypass these application policies and does not provide those workflow guarantees.

There is no double-entry reconciliation or accounting representation of external
counterparties. Consistency depends on controlled transaction execution and known
opening balances. This is a comparison mechanism, not a replay engine, and it
cannot reconstruct existing history when the opening is unknown.

Unit and isolated PostgreSQL tests cover zero/explicit/historical initialization,
immutable domain behavior, currency, missing accounts/balances, insufficient funds,
duplicate initialization, atomic creation, rollback, lock requirements, concurrent
credits/debits with observed PostgreSQL lock waits, consistency and migrations.
