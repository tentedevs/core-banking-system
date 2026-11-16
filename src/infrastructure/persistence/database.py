from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.settings import Settings


def create_database_engine(settings: Settings) -> Engine:
    """Create a lazy engine; no connection, tables or migrations are created here."""
    return create_engine(
        settings.postgresql_url(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Use `with sessions() as session:` to obtain a fresh, automatically closed session."""
    return sessionmaker(bind=engine, expire_on_commit=False)
