import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text

from api.dependencies import SessionDependency
from api.main import create_app
from infrastructure.persistence.database import create_database_engine
from infrastructure.persistence.migrate import initialize_database
from infrastructure.settings import Settings

pytestmark = pytest.mark.integration


def test_migrations_are_repeatable(migrated_engine: Engine) -> None:
    initialize_database(migrated_engine)
    with migrated_engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        assert inspect(connection).get_table_names(schema="banking") == ["accounts"]


def test_api_postgres_session_and_health(isolated_database_settings: Settings) -> None:
    settings = Settings(
        persistence_backend="postgres",
        database_url=isolated_database_settings.database_url,
        _env_file=None,
    )
    app = create_app(settings)

    @app.get("/session-probe")
    def probe(session: SessionDependency) -> dict[str, int | None]:
        assert session is not None
        return {"value": session.scalar(text("SELECT 1"))}

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/session-probe").json() == {"value": 1}


def test_request_transactions(isolated_database_settings: Settings) -> None:
    # Temporary table in a unique test schema; never a business migration.
    admin = create_database_engine(isolated_database_settings)
    try:
        with admin.begin() as connection:
            connection.execute(text("CREATE TABLE infrastructure_probe (value integer)"))
        app = create_app(
            Settings(
                persistence_backend="postgres",
                database_url=isolated_database_settings.database_url,
                _env_file=None,
            )
        )

        @app.post("/session-probe/{value}")
        def write(value: int, session: SessionDependency) -> dict[str, str]:
            assert session is not None
            session.execute(text("INSERT INTO infrastructure_probe VALUES (:v)"), {"v": value})
            if value == 2:
                raise ValueError("rollback probe")
            return {"status": "ok"}

        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.post("/session-probe/1").status_code == 200
            assert client.post("/session-probe/2").status_code == 500
        with admin.connect() as connection:
            assert connection.scalars(text("SELECT value FROM infrastructure_probe")).all() == [1]
    finally:
        admin.dispose()
