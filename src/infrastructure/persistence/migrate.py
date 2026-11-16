"""Explicit schema operations, independent of FastAPI and safe to repeat."""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.persistence.database import create_database_engine
from infrastructure.settings import Settings


class SchemaInitializationError(RuntimeError):
    pass


def alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"), stdout=sys.stdout)


def verify_head(connection: Connection, config: Config) -> None:
    current = set(MigrationContext.configure(connection).get_current_heads())
    expected = set(ScriptDirectory.from_config(config).get_heads())
    if current != expected:
        raise SchemaInitializationError("Database revision does not match the Alembic head")


def initialize_database(engine: Engine) -> None:
    config = alembic_config()
    # Check connectivity, apply revisions and check head in one transaction.
    with engine.begin() as connection:
        if connection.scalar(text("SELECT 1")) != 1:
            raise SchemaInitializationError("Database connectivity check failed")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        verify_head(connection, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("init", "migrate", "current", "history"))
    operation = parser.parse_args(argv).operation
    engine: Engine | None = None
    try:
        config = alembic_config()
        if operation == "history":
            command.history(config)
            return 0
        engine = create_database_engine(Settings(database_mode="postgres"))
        if operation == "current":
            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.current(config)
        else:
            initialize_database(engine)
            print("Database initialized: migration history verified.")
        return 0
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            print(f"Database configuration error: {error['msg']}", file=sys.stderr)
    except SQLAlchemyError:
        print(
            "Database operation failed. Check PostgreSQL readiness, DATABASE_URL, credentials "
            "and schema permissions. No database reset was performed.",
            file=sys.stderr,
        )
    except (CommandError, SchemaInitializationError):
        print(
            "Schema initialization failed. Check migration history and the current revision.",
            file=sys.stderr,
        )
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
