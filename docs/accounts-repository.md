# Accounts repository — Phase 3

`ports/account_repository.py` defines the domain-facing `AccountRepository`
Protocol. This follows CRP's repository interface location and structural
typing convention rather than introducing an ABC or a second interface under
`domain/`. The port imports only standard Python types and Account; it exposes
no ORM, session or HTTP objects. The product remains `SAVINGS_ACCOUNT` only.

`infrastructure/persistence/repositories/account_repository.py` supplies
`SQLAlchemyAccountRepository`, using the existing AccountORM and bidirectional
mapper. The constructor receives the caller's Session. CRP has no separate Unit
of Work abstraction; Phase 3 did not add one or alter API injection. Phase 4
introduces a minimal [application transaction boundary](accounts-application.md).

The five Phase 3 operations are:

- `save(account)`: check for an existing UUID with Session.get, add a mapped row
  for a new identity, or explicitly update status, closed_at and updated_at.
  Existing customer, account number, product, currency, opening date and creation
  timestamp are retained, even if a caller supplies a different reconstructed
  snapshot. The repository does not introduce transition validation.
- `get_by_id(account_id)` and `get_by_account_number(account_number)`: return a
  mapped Account or None.
- `list_by_customer(customer_id, limit=50, offset=0)` and
  `list_all(limit=50, offset=0)`: return domain entities ordered by UUID ascending.
  Both require integer limits from 1 to 100 and non-negative integer offsets;
  booleans are rejected. These bounds follow CRP's pagination validation style
  and maximum page size, applied here because repository pagination is exposed
  directly without an application use case.

The adapter does not call commit, rollback, close, merge, or an explicit flush.
It uses the existing Session's normal autoflush; the caller may flush to force
database checks, or commit through its transaction boundary. Multiple operations
and repository instances can share one Session and transaction. Database failures
propagate unchanged, including uniqueness violations, and require caller-managed
rollback. No uniqueness precheck, error-to-domain conversion or HTTP handling is
introduced. PostgreSQL remains responsible for uniqueness and data constraints.

All statuses, including historical CLOSED accounts, remain queryable. There is
no delete operation. No account closure operation, repository factory, generic
repository, in-memory adapter, use case, endpoint, schema change or seed is added.

Phase 4 adds `get_by_id_for_update` to read current state under a row lock for
application state changes. It also adds AccountNumberConflict at the port,
translated by the Unit of Work after rollback; direct repository errors retain
the Phase 3 behavior.

Integration tests reuse the existing disposable PostgreSQL database fixtures.
They verify every persisted field, customer filtering, stable pagination,
bounded default pages, block/reactivate updates without INSERT, original-field
preservation, historical CLOSED accounts, repeated saves, visibility between
sessions, caller commit and rollback, failed transaction atomicity, and unchanged
database exceptions. Unit tests reject invalid pagination before SQL access.
CRP and development data remain untouched.
