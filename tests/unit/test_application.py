import importlib
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from api.dependencies import SessionDependency
from api.main import create_app
from infrastructure.persistence.models import Base
from infrastructure.settings import Settings


def test_application_creation_and_health() -> None:
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert app.title == "Core Banking System"
        assert app.state.session_factory is None
        paths = client.get("/openapi.json").json()["paths"]
        assert set(paths) == {"/health"}


def test_postgres_lifecycle_is_lazy_and_disposes_engine() -> None:
    # The unused port is never contacted: liveness does not assert DB readiness.
    settings = Settings(
        persistence_backend="postgres",
        database_url="postgresql+psycopg://unused@127.0.0.1:1/core_banking_test",
        _env_file=None,
    )
    app = create_app(settings)
    engine = app.state.session_factory.kw["bind"]
    with patch.object(engine, "dispose", wraps=engine.dispose) as dispose:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert engine.pool.checkedout() == 0
        dispose.assert_called_once()


def test_database_errors_are_redacted() -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/infrastructure-probe")
    def probe() -> None:
        raise OperationalError("private SQL", {}, Exception("private credentials"))

    with TestClient(app) as client:
        response = client.get("/infrastructure-probe")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database operation unavailable"}


def test_memory_session_dependency_yields_none() -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/session-probe")
    def probe(session: SessionDependency) -> dict[str, bool]:
        return {"disabled": session is None}

    with TestClient(app) as client:
        assert client.get("/session-probe").json() == {"disabled": True}


def test_import_integrity_and_registered_metadata() -> None:
    for package in ("domain", "application", "ports", "api", "infrastructure"):
        assert importlib.import_module(package).__file__ is not None
    assert not Base.metadata.tables
