# Repository guide

- Keep the initialization scope minimal; no future business modules in advance.
- Python 3.12+, uv dependency management, and committed uv.lock.
- Code in src/; tests in tests/unit and tests/integration.
- Domain logic stays independent of API and infrastructure.
- Never commit credentials or datasets.
- Run make check after code changes; PostgreSQL integration tests require a dedicated _test database.
- The Credit Risk Platform reference is read-only and is not a runtime dependency.
