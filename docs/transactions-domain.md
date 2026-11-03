# Transactions domain — Phase 1 (no ledger)

`domain/transaction/` follows the Accounts conventions: frozen dataclasses in
`entities.py`, StrEnum definitions in `enums.py`, domain-specific ValueError
subclasses in `exceptions.py`, constructor validation and parametrized pytest
tests. No Accounts implementation or CRP files are modified.

BankingTransaction represents an operation. AccountMovement represents one
account-side effect referencing that operation. There is no double-entry ledger
in this MVP. Future application operations will coordinate movements and an
AccountBalance projection atomically through PostgreSQL; neither is implemented
here.

Phase 2 adds a separate [persistence representation](transactions-persistence.md),
leaving these domain entities and their precision rules unchanged.

## Transactions

BankingTransaction contains the requested identity, type, status, monetary and
currency fields, optional description, effective/posting/creation timestamps,
optional idempotency key and optional reversal reference. `create()` generates a
new UUID and UTC created_at and always returns PENDING with no posted_at. The
caller supplies effective_at explicitly, as Account.create requires opened_at.

Direct construction validates historical snapshots without resetting UUIDs,
state, timestamps, precision or optional values. Valid types are DEPOSIT,
WITHDRAWAL and TRANSFER; states are PENDING, POSTED, REJECTED and REVERSED.
POSTED requires posted_at. REVERSED describes a previously posted operation and
therefore retains its posting timestamp. PENDING and REJECTED cannot have one.
As with Accounts, timestamp fields require datetime instances; creation uses UTC
and reconstruction preserves supplied datetimes, including their timezone
offsets, without normalization or additional chronology rules.

Amounts must be finite positive Decimals; float/int/string inputs, NaN and
infinities are rejected. No scale, rounding or two-decimal-place restriction is
invented. Currency follows Accounts exactly: three uppercase ASCII letters,
without verified ISO 4217 membership. UUID strings and raw enum strings require
conversion at a future boundary before domain construction.

Every field is frozen, including posted financial details. There is no post,
reject, reverse or balance-update operation on the entity. The validated
constructor is a reconstruction mechanism, not authorization to post money.
Posting must later be coordinated in an application transaction with balances
and movements; no domain method in this phase can perform that operation.

`reversal_of_id` is metadata for a distinct compensating transaction referencing
an original transaction. It must be a UUID and cannot reference itself. A new
compensating snapshot still starts PENDING and has no financial effects. The
original's REVERSED status does not require a reversal_of_id: that link belongs
on the compensation. No reversal execution, reference lookup or reversal amount/
currency validation is implemented. Idempotency keys are optional text metadata;
there is no idempotency storage or uniqueness enforcement in the domain.

## Account movements and relationships

AccountMovement validates UUID identity and transaction/account references,
CREDIT/DEBIT direction, finite positive Decimal amount, datetime booked_at and
optional text metadata. `create()` generates only its UUID. Direct construction
preserves normalized historical data. All fields are immutable.

CREDIT means money enters a customer account; DEBIT means money leaves it.
Both use positive amounts. balance_after is either None or a finite Decimal;
negative historical values are explicitly accepted and preserved. It is an
observed value supplied by the caller, not a balance the movement calculates.
The entity never reads or updates an account or balance projection.

The conceptual relationship is one transaction to potentially multiple movements:

| Operation | Movements when successfully posted |
| --- | --- |
| Deposit | One CREDIT |
| Withdrawal | One DEBIT |
| Internal transfer | One DEBIT and one CREDIT referencing the same transaction |
| Rejected operation | None |

These are future application posting rules, not constructor cardinality checks.
An individual movement with a transaction UUID cannot independently verify its
parent's status, the complete set of sibling movements, account existence,
currency compatibility or sufficient funds. Rejected operations must not produce
posted movements when that coordination is implemented. This phase creates no
movements automatically and provides no aggregate posting API.

The entities contain no SQLAlchemy, FastAPI, Pydantic, Alembic, repositories,
AccountBalance implementation, source-specific IDs, dataset codes, parsing,
simulation or loader behavior.
