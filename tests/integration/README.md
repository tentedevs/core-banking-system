# PostgreSQL integration tests

These tests require a real, dedicated database whose name ends in `_test`.
They do not require CRP or write to the development schema. Missing
TEST_DATABASE_URL skips the suite; a configured but broken database fails.

Using the CBS development service, create a separate test database once:

```sh
make db-up
make db-shell
```

Inside psql:

```sql
CREATE DATABASE core_banking_test;
\q
```

Set TEST_DATABASE_URL in the ignored root .env or process environment:

```sh
TEST_DATABASE_URL=postgresql+psycopg://corebanking:change_me_for_cbs_local_development@localhost:5433/core_banking_test make test-integration
```

The test role needs CREATEDB permission. The configured database name must end
in `_test`; development URLs are refused.
Tests perform real SELECT 1 checks and verify failure on an unavailable port.
Migration, Accounts and API tests create a unique `cbs_<uuid>_test` database per
test and drop only that database afterward. Whole-database isolation is necessary
because `banking.accounts` has an explicit schema; a unique search_path would not
isolate it. The configured test database is used for connectivity and database
creation only. The existing engine and session helpers are reused.

The suite covers account mapping through PostgreSQL, status updates, raw SQL
constraint violations, server defaults, customer indexing, column types,
metadata parity, repeatable upgrades, downgrade/re-upgrade, and preservation of
unrelated objects and pre-existing account data. A temporary infrastructure
table verifies request commits/rollbacks. No successful connection is mocked,
and no SQLite substitute is used. Mapper-only tests also run without a database
in `tests/unit/test_account_mapper.py`.

Repository tests cover insert/update behavior, lookups, customer filtering,
UUID ordering, pagination, immutable-field preservation and historical CLOSED
records. Separate sessions verify that writes remain invisible until the caller
commits. Database errors and caller aborts roll back the whole transaction;
the adapter never owns commit, rollback or session close. Pagination validation
also runs without PostgreSQL in `tests/unit/test_account_repository.py`.

Application tests cover all six use cases through SQLAlchemyAccountUnitOfWork,
explicit write commits, no read commits, transaction rollback, uniqueness
conflicts, and Session release. Concurrent block/reactivate tests observe real
PostgreSQL lock waits and verify the waiting operation validates freshly committed
state. Unit tests use test-only doubles in `tests/account_fakes.py`.

`test_accounts_api.py` exercises all six HTTP endpoints against PostgreSQL with
the production dependency chain. It checks committed rows from a separate
connection, matching totals and customer filtering, duplicate-number 409 errors,
rejected transitions and invalid input, no read commits and released connections.
The API does not run migrations itself; the existing migrated fixture prepares
the disposable database. HTTP tests without PostgreSQL live in
`tests/unit/test_accounts_api.py` and use FastAPI dependency overrides.
