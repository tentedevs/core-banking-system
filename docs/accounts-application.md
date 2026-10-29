# Accounts application — Phase 4

Six constructor-injected classes in `application/use_cases/` follow CRP's
`execute()` convention and return domain Account entities or lists. Inputs are
frozen standard-library dataclasses in `application/account_messages.py`:

| Use case | Input | Behavior |
| --- | --- | --- |
| CreateAccount | CreateAccountCommand(customer_id, currency="CZK") | Create and commit an ACTIVE savings account |
| GetAccount | GetAccountQuery(account_id) | Read by UUID |
| GetAccountByNumber | GetAccountByNumberQuery(account_number) | Read by number |
| ListAccounts | ListAccountsQuery(customer_id=None, limit=50, offset=0) | Page all accounts or filter by customer in SQL |
| BlockAccount | BlockAccountCommand(account_id) | Lock, invoke domain block, save and commit |
| ReactivateAccount | ReactivateAccountCommand(account_id) | Lock, invoke domain reactivate, save and commit |

Messages validate UUIDs, nonblank lookup numbers and pagination (integer limit
1–100 and offset >= 0; booleans rejected). Currency is validated by Account's
factory, which also supplies identity, ACTIVE status and aware audit timestamps.
The opening date uses UTC. Missing records raise AccountNotFound alongside
GetAccount, following CRP's GetApplication/ApplicationNotFound convention.
Invalid transitions preserve domain exceptions.

The product remains `SAVINGS_ACCOUNT`, as confirmed for this phase. Customer
identity is validated only as a UUID; existence is not checked. There is no
Customer table, CRP query, HTTP client or integration adapter. The supplied
specification ends mid-sentence in the customer integration section; this
implementation covers its six complete use cases and transaction requirements.

## Transactions

CRP has no Unit of Work; its API owns Session transaction contexts. To let these
application operations complete transactions without SQLAlchemy dependencies,
`ports/account_unit_of_work.py` defines a minimal AccountUnitOfWork Protocol.
All use cases accept it by constructor injection. Neither application nor domain
imports SQLAlchemy, PostgreSQL, FastAPI or Pydantic.

SQLAlchemyAccountUnitOfWork receives the existing create_session_factory result.
Each context opens one Session and repository. Writes call commit after all
operations succeed; exit rolls back any remaining transaction and closes the
Session, including after commit failures. Reads never commit; their normal
SQLAlchemy read transaction is rolled back on exit. Exiting without commit
discards writes. Multiple repository operations share this transaction.
Repositories still never commit, rollback or close the Session.

Composition code passes an instance to the use case. Instances may be reused
sequentially, but cannot be nested or shared concurrently. No second engine,
session factory or API dependency is introduced.

## Internal numbers and collisions

AccountNumberGenerator is a small port. InternalAccountNumberGenerator produces
`C` followed by UUID4 hexadecimal text: 33 characters within VARCHAR(34). These
are internal references, not IBANs or real banking account numbers.

PostgreSQL's unique constraint is the final protection against collisions. After
rollback and cleanup, the Unit of Work converts only a psycopg UniqueViolation
naming `uq_accounts_account_number` into AccountNumberConflict(ValueError),
defined at the repository port. This covers autoflush, explicit flush and commit
failures. Other database errors propagate unchanged. There is no preliminary
uniqueness check or automatic retry loop.

## Concurrent state changes

Following CRP's evaluation row lock, AccountRepository now also exposes
get_by_id_for_update. BlockAccount and ReactivateAccount lock before reading and
validating state, retaining the lock until commit/rollback. The SQLAlchemy query
uses populate_existing=True so previously loaded ORM identities are refreshed.
Under the existing PostgreSQL READ COMMITTED isolation, a competing operation
waits and then validates the winner's committed state. Repeated block/reactivate
operations fail the domain rule instead of overwriting intervening updates.

Plain reads remain unlocked. Future read-modify-write use cases must use this
locking boundary: low-level repository save alone does not protect stale snapshots.

## Verification and scope

Unit tests use test-only transaction/repository doubles. Real PostgreSQL tests
verify lifecycle operations, filtering and pagination, no read commits, rollback
across multiple writes, typed number collisions, session cleanup, refreshed stale
identities, and observed row-lock waits for both block and reactivate. Earlier
domain, mapper, repository and migration tests remain in the verification suite.

Phase 5 adds the [REST endpoints](accounts-api.md), and extends ListAccounts with
execute_with_total while retaining execute's list result. Frontend, imports,
seeds, customer tables, closure, balances, transactions, ledger and interest
features remain deferred.
