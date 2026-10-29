# Independent PostgreSQL service

```sh
make env-init
# Edit database/.env and the matching root DATABASE_URL if needed.
make db-config
make db-up
make db-ready
make db-check
make db-init
make db-status
make db-down
```

Run these commands from the project root. Docker Compose v2 and a running daemon
are required. `db-config` validates configuration without printing credentials.
`db-up` waits up to 120 seconds for health. `db-down` stops the service and keeps
its volume. `db-restart` restarts and waits for health; `db-shell` opens psql;
`db-logs` follows logs. No command resets the development database.

Project: core-banking-db. Image: postgres:16. Host: 127.0.0.1:5433.
Default volume: core-banking-system_postgres_data. Credentials/name/port/volume
are provided by database/.env (ignored by Git). No CRP volume is reused.
Avoid overriding these identifiers with CRP resource names. Existing volume
credentials do not change when editing POSTGRES_USER/POSTGRES_PASSWORD.

The root .env configures SQLAlchemy separately. With example settings it uses
corebanking on localhost:5433. SQLAlchemy checks SELECT 1 with the actual user,
password and database. Unlike pg_isready, this validates authentication and query
execution. All migrations remain explicit; `0001_create_accounts` creates
`banking.accounts` for the `SAVINGS_ACCOUNT` product.

## Isolated service test

`make db-test` uses a unique Compose project, volume, temporary environment file,
_test database, and dynamically assigned host port. It starts the service twice,
checks credentials, creates a disposable infrastructure probe table, restarts,
verifies persistence, and drops that table. It stops its own project afterward;
like CRP, it preserves the test volume and reports its name. It does not use the
development database or call SQLAlchemy. For Python connectivity and transaction
checks follow [integration instructions](../tests/integration/README.md).
