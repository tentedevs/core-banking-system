import socket
from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool

from infrastructure.persistence.check_db import check_connection
from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(test_settings: Settings) -> Iterator[Engine]:
    engine = create_database_engine(test_settings)
    try:
        yield engine
    finally:
        engine.dispose()


def test_select_one_against_postgresql_and_release_connection(engine: Engine) -> None:
    check_connection(create_session_factory(engine))
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.checkedout() == 0


def test_postgresql_unavailable_raises(test_settings: Settings) -> None:
    # Reserve a local port without listening so no other service can occupy it.
    with socket.socket() as reserved_port:
        reserved_port.bind(("127.0.0.1", 0))
        url = test_settings.postgresql_url().set(
            host="127.0.0.1", port=reserved_port.getsockname()[1], query={}
        )
        settings = Settings(
            database_mode="postgres",
            database_url=SecretStr(url.render_as_string(hide_password=False)),
            _env_file=None,
        )
        engine = create_database_engine(settings)
        try:
            with pytest.raises(OperationalError):
                check_connection(create_session_factory(engine))
        finally:
            engine.dispose()
