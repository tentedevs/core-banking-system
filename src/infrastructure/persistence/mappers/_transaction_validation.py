from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect
from sqlalchemy.orm import InstanceState

from infrastructure.persistence.models import AccountMovementORM, TransactionORM

_MAX_MONEY = Decimal("9999999999999999.99")


def require_loaded(model: TransactionORM | AccountMovementORM) -> None:
    state = inspect(model)
    assert isinstance(state, InstanceState)
    if state.unloaded:
        raise ValueError("Mapping requires an ORM object with all persisted fields loaded")


def require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime for persistence")


def require_money(value: Decimal, field: str) -> None:
    """Refuse silent rounding/overflow without changing the domain Decimal or context."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal for NUMERIC(18,2)")
    parts = value.as_tuple()
    assert isinstance(parts.exponent, int)
    if value.copy_abs() > _MAX_MONEY or (
        parts.exponent < -2 and any(parts.digits[parts.exponent + 2 :])
    ):
        raise ValueError(f"{field} cannot be represented exactly as NUMERIC(18,2)")
