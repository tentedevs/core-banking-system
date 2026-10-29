# Accounts persistence — Phase 2

`AccountORM` lives in the existing `infrastructure/persistence/models.py` and
uses the shared Base. It defines `banking.accounts` with UUID identifiers,
VARCHAR(34) account numbers, VARCHAR(30) product type, CHAR(3) currency,
VARCHAR(20) status, DATE lifecycle fields and timezone-aware audit timestamps.
Only `closed_at` is nullable. The customer UUID has a B-tree index and has no
foreign key, local Customer model or ORM relationship.

As in CRP, product and status use SQLAlchemy non-native Enum mappings over
VARCHAR, with named CHECK constraints. Database defaults are `SAVINGS_ACCOUNT`
and `ACTIVE`. Additional constraints enforce unique and nonblank account
numbers, uppercase three-letter currency format, valid closing dates, and
equivalence between CLOSED status and presence of a closing date. Currency ISO
membership remains unverified. The database caps account numbers at 34
characters; the Phase 1 domain still accepts any nonblank number.

The functions in `infrastructure/persistence/mappers/account_mapper.py` copy
every persisted field. Reconstruction calls the validated Account constructor,
never its creation factory, preserving identity and historical state. Both
mapping directions require aware timestamps; they retain supplied timezone
offsets, while PostgreSQL preserves the represented instant. Mapping unloaded
or expired ORM fields fails before implicit SQL can run. There are no business
operations on the ORM model and no SQLAlchemy dependency in the domain.

The product enum and domain factory default now use `SAVINGS_ACCOUNT` only.
Neither `CURRENT_ACCOUNT` nor the previous `SAVING_ACCOUNT` spelling is accepted.
No savings-specific behavior is introduced.

Revision `0001_create_accounts` is handwritten and uses explicit types and named
constraints. It creates the banking schema if absent, the table, and the customer
index. The model is registered on the Base metadata already used by Alembic;
schema reflection is enabled for autogeneration. Upgrade is transactional and
the initialization command verifies the applied head. Downgrade removes the
table and index while preserving the schema, which may contain other modules.

There were no pre-existing CBS business revisions when this phase began. If an
unmanaged accounts table already exists, upgrade fails and rolls back rather
than adopting, rewriting or dropping it. Inspect that database and plan a
separate reviewed data migration before retrying; this initial revision does
not convert existing CURRENT_ACCOUNT rows.

Apply to the intended database explicitly with `make db-migrate` or
`make db-init`; startup does not apply migrations. See the
[integration instructions](../tests/integration/README.md) for isolated tests.
The tests execute upgrades and downgrades against real PostgreSQL, compare
metadata and server defaults, inspect types and constraints, verify usable
customer indexing, and bypass Python enum validation to test database checks.

Repositories were outside Phase 2 and are now implemented separately in
[Phase 3](accounts-repository.md). Application use cases are implemented in
[Phase 4](accounts-application.md). APIs, frontend, data initialization, balances,
transactions, ledger and account closure remain deferred.
