import sys

from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.settings import Settings


class DatabaseCheckError(RuntimeError):
    pass


def check_connection(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        if session.scalar(text("SELECT 1")) != 1:
            raise DatabaseCheckError("PostgreSQL check failed: SELECT 1 did not return 1")


def main() -> int:
    engine: Engine | None = None
    try:
        # This utility explicitly checks PostgreSQL, even when the API uses memory.
        settings = Settings(database_mode="postgres")
        engine = create_database_engine(settings)
        check_connection(create_session_factory(engine))
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            print(f"Database configuration error: {error['msg']}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        # Driver exceptions may contain connection details; never print their raw text.
        print(
            "PostgreSQL connection failed. Run make db-up and check DATABASE_URL, "
            "credentials and the database name.",
            file=sys.stderr,
        )
        return 1
    except DatabaseCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print("PostgreSQL connection OK (SELECT 1 = 1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
