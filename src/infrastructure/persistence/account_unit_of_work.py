from types import TracebackType
from typing import Self

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository
from ports.account_repository import AccountNumberConflict


class SQLAlchemyAccountUnitOfWork:
    """Own one Session from the existing factory; repositories never commit."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self._session: Session | None = None
        self._accounts: SQLAlchemyAccountRepository | None = None

    @property
    def accounts(self) -> SQLAlchemyAccountRepository:
        if self._accounts is None:
            raise RuntimeError("Unit of work must be entered before accessing accounts")
        return self._accounts

    def __enter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of work is already active")
        self._session = self.sessions()
        self._accounts = SQLAlchemyAccountRepository(self._session)
        return self

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work must be entered before committing")
        self._session.commit()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            return
        try:
            session.rollback()
        finally:
            try:
                session.close()
            finally:
                self._session = None
                self._accounts = None
        # Include errors from autoflush, explicit flush, and commit in this boundary.
        if (
            isinstance(exc_value, IntegrityError)
            and isinstance(exc_value.orig, UniqueViolation)
            and exc_value.orig.diag.constraint_name == "uq_accounts_account_number"
        ):
            raise AccountNumberConflict("Account number is already in use") from exc_value
