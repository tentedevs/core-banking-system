from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.account.entities import Account
from infrastructure.persistence.mappers import account_mapper
from infrastructure.persistence.models import AccountORM


class SQLAlchemyAccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, account: Account) -> None:
        values = account_mapper.to_orm(account)
        row = self.session.get(AccountORM, account.id)
        if row is None:
            self.session.add(values)
            return
        # Persist lifecycle state only; retain the original account attributes.
        row.status = values.status
        row.closed_at = values.closed_at
        row.updated_at = values.updated_at

    def get_by_id(self, account_id: UUID) -> Account | None:
        row = self.session.get(AccountORM, account_id)
        return account_mapper.to_domain(row) if row is not None else None

    def get_by_id_for_update(self, account_id: UUID) -> Account | None:
        row = self.session.scalar(
            select(AccountORM)
            .where(AccountORM.id == account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return account_mapper.to_domain(row) if row is not None else None

    def get_by_account_number(self, account_number: str) -> Account | None:
        row = self.session.scalar(
            select(AccountORM).where(AccountORM.account_number == account_number)
        )
        return account_mapper.to_domain(row) if row is not None else None

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")

    def list_by_customer(
        self, customer_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Account]:
        self._validate_pagination(limit, offset)
        query = (
            select(AccountORM)
            .where(AccountORM.customer_id == customer_id)
            .order_by(AccountORM.id)
            .limit(limit)
            .offset(offset)
        )
        return [account_mapper.to_domain(row) for row in self.session.scalars(query)]

    def list_all(self, limit: int = 50, offset: int = 0) -> list[Account]:
        self._validate_pagination(limit, offset)
        query = select(AccountORM).order_by(AccountORM.id).limit(limit).offset(offset)
        return [account_mapper.to_domain(row) for row in self.session.scalars(query)]
