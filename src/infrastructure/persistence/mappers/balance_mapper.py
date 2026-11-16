from sqlalchemy import inspect

from domain.account_balance.entities import AccountBalance, BalanceOpening
from domain.account_balance.enums import BalanceInitializationPolicy
from infrastructure.persistence.mappers._transaction_validation import require_aware, require_money
from infrastructure.persistence.models import AccountBalanceORM, BalanceOpeningORM


def to_orm(balance: AccountBalance) -> AccountBalanceORM:
    require_money(balance.booked_balance, "booked_balance")
    require_money(balance.available_balance, "available_balance")
    require_aware(balance.updated_at, "updated_at")
    return AccountBalanceORM(
        account_id=balance.account_id,
        booked_balance=balance.booked_balance,
        available_balance=balance.available_balance,
        updated_at=balance.updated_at,
    )


def to_domain(row: AccountBalanceORM) -> AccountBalance:
    if inspect(row).unloaded:
        raise ValueError("Mapping requires an ORM object with all persisted fields loaded")
    require_money(row.booked_balance, "booked_balance")
    require_money(row.available_balance, "available_balance")
    require_aware(row.updated_at, "updated_at")
    return AccountBalance(row.account_id, row.booked_balance, row.available_balance, row.updated_at)


def opening_to_orm(opening: BalanceOpening) -> BalanceOpeningORM:
    require_money(opening.opening_balance, "opening_balance")
    require_aware(opening.initialized_at, "initialized_at")
    return BalanceOpeningORM(
        account_id=opening.account_id,
        opening_balance=opening.opening_balance,
        policy=opening.policy,
        initialized_at=opening.initialized_at,
    )


def opening_to_domain(row: BalanceOpeningORM) -> BalanceOpening:
    if inspect(row).unloaded:
        raise ValueError("Mapping requires an ORM object with all persisted fields loaded")
    require_money(row.opening_balance, "opening_balance")
    require_aware(row.initialized_at, "initialized_at")
    return BalanceOpening(
        row.account_id,
        row.opening_balance,
        BalanceInitializationPolicy(row.policy),
        row.initialized_at,
    )
