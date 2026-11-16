from alembic import context
from sqlalchemy import Connection

from infrastructure.persistence.database import create_database_engine
from infrastructure.persistence.models import Base
from infrastructure.settings import Settings

config = context.config
target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    url = Settings(database_mode="postgres").postgresql_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_schemas=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
    else:
        engine = create_database_engine(Settings(database_mode="postgres"))
        try:
            with engine.connect() as connection:
                run_migrations(connection)
        finally:
            engine.dispose()
