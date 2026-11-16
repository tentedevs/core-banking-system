from datetime import datetime

from sqlalchemy import inspect

from domain.account.entities import Account
from domain.account.enums import AccountProductType, AccountStatus
from infrastructure.persistence.models import AccountORM


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime for persistence")


def to_orm(account: Account) -> AccountORM:
    _require_aware(account.created_at, "created_at")
    _require_aware(account.updated_at, "updated_at")
    return AccountORM(
        id=account.id,
        customer_id=account.customer_id,
        account_number=account.account_number,
        product_type=account.product_type,
        currency=account.currency,
        status=account.status,
        opened_at=account.opened_at,
        closed_at=account.closed_at,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def to_domain(account_orm: AccountORM) -> Account:
    # As in CRP, reject unloaded fields before attribute access can issue SQL.
    if inspect(account_orm).unloaded:
        raise ValueError("Mapping requires an ORM object with all persisted fields loaded")
    _require_aware(account_orm.created_at, "created_at")
    _require_aware(account_orm.updated_at, "updated_at")
    return Account(
        id=account_orm.id,
        customer_id=account_orm.customer_id,
        account_number=account_orm.account_number,
        product_type=AccountProductType(account_orm.product_type),
        currency=account_orm.currency,
        status=AccountStatus(account_orm.status),
        opened_at=account_orm.opened_at,
        closed_at=account_orm.closed_at,
        created_at=account_orm.created_at,
        updated_at=account_orm.updated_at,
    )
