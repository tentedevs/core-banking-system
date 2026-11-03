from decimal import Decimal
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransaction

from domain.account_balance.entities import AccountBalance, BalanceOpening
from domain.account_balance.enums import BalanceInitializationPolicy
from domain.transaction.enums import MovementDirection, TransactionStatus
from infrastructure.persistence.mappers import balance_mapper
from infrastructure.persistence.models import (
    AccountBalanceORM,
    AccountMovementORM,
    BalanceOpeningORM,
    TransactionORM,
)
from ports.balance_repository import (
    BalanceAlreadyInitialized,
    BalanceCurrencyMismatch,
    BalanceLockRequired,
    PostedMovementSummary,
)


class SQLAlchemyBalanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._locks: dict[
            UUID, tuple[SessionTransaction, SessionTransaction | None, AccountBalanceORM]
        ] = {}

    def get_by_account_id(self, account_id: UUID) -> AccountBalance | None:
        row = self.session.get(AccountBalanceORM, account_id)
        return balance_mapper.to_domain(row) if row is not None else None

    def create_initial_balance(
        self,
        account_id: UUID,
        initial_balance: Decimal = Decimal("0"),
        *,
        policy: BalanceInitializationPolicy = BalanceInitializationPolicy.ORDINARY,
    ) -> AccountBalance:
        if self.get_by_account_id(account_id) is not None:
            raise BalanceAlreadyInitialized("Account balance is already initialized")
        balance = AccountBalance.create_initial(account_id, initial_balance, policy=policy)
        row = balance_mapper.to_orm(balance)
        opening = balance_mapper.opening_to_orm(
            BalanceOpening(account_id, initial_balance, policy, balance.updated_at)
        )
        try:
            self.session.add(row)
            self.session.flush()
            self.session.add(opening)
            self.session.flush()
        except IntegrityError as exc:
            if isinstance(exc.orig, UniqueViolation) and exc.orig.diag.constraint_name in (
                "pk_account_balances",
                "pk_account_balance_openings",
            ):
                raise BalanceAlreadyInitialized("Account balance is already initialized") from exc
            raise
        return balance

    def get_for_update(self, account_id: UUID) -> AccountBalance | None:
        row = self.session.scalar(
            select(AccountBalanceORM)
            .where(AccountBalanceORM.account_id == account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        transaction = self.session.get_transaction()
        assert transaction is not None
        self._locks[account_id] = (transaction, self.session.get_nested_transaction(), row)
        return balance_mapper.to_domain(row)

    def persist_updated_balance(self, balance: AccountBalance) -> None:
        lock = self._locks.get(balance.account_id)
        if (
            lock is None
            or lock[0] is not self.session.get_transaction()
            or lock[1] is not self.session.get_nested_transaction()
        ):
            raise BalanceLockRequired(
                "Balance update requires a row lock in the same active transaction"
            )
        values = balance_mapper.to_orm(balance)
        row = lock[2]
        row.booked_balance = values.booked_balance
        row.available_balance = values.available_balance
        row.updated_at = values.updated_at
        self.session.flush()

    def get_opening(self, account_id: UUID) -> BalanceOpening | None:
        row = self.session.get(BalanceOpeningORM, account_id)
        return balance_mapper.opening_to_domain(row) if row is not None else None

    def get_posted_movement_summary(self, account_id: UUID, currency: str) -> PostedMovementSummary:
        signed = case(
            (AccountMovementORM.direction == MovementDirection.CREDIT, AccountMovementORM.amount),
            else_=-AccountMovementORM.amount,
        )
        query = (
            select(
                func.coalesce(func.sum(signed), Decimal("0")).label("total"),
                func.count(AccountMovementORM.id).label("movement_count"),
                func.count(AccountMovementORM.id)
                .filter(TransactionORM.currency != currency)
                .label("mismatched"),
            )
            .select_from(AccountMovementORM)
            .join(TransactionORM, TransactionORM.id == AccountMovementORM.transaction_id)
            .where(
                AccountMovementORM.account_id == account_id,
                TransactionORM.status.in_([TransactionStatus.POSTED, TransactionStatus.REVERSED]),
                TransactionORM.posted_at.is_not(None),
            )
        )
        row = self.session.execute(query).one()
        if row.mismatched:
            raise BalanceCurrencyMismatch(
                "Posted movements contain a different currency from the account"
            )
        return PostedMovementSummary(Decimal(row.total), int(row.movement_count))
