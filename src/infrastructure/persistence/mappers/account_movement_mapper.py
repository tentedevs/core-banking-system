from domain.transaction.entities import AccountMovement
from domain.transaction.enums import MovementDirection
from infrastructure.persistence.mappers._transaction_validation import (
    require_aware,
    require_loaded,
    require_money,
)
from infrastructure.persistence.models import AccountMovementORM


def _validate_storage(movement: AccountMovement | AccountMovementORM) -> None:
    require_money(movement.amount, "amount")
    if movement.balance_after is not None:
        require_money(movement.balance_after, "balance_after")
    require_aware(movement.booked_at, "booked_at")


def to_orm(movement: AccountMovement) -> AccountMovementORM:
    _validate_storage(movement)
    return AccountMovementORM(
        id=movement.id,
        transaction_id=movement.transaction_id,
        account_id=movement.account_id,
        direction=movement.direction,
        amount=movement.amount,
        balance_after=movement.balance_after,
        category=movement.category,
        counterparty_account=movement.counterparty_account,
        counterparty_bank=movement.counterparty_bank,
        booked_at=movement.booked_at,
    )


def to_domain(movement: AccountMovementORM) -> AccountMovement:
    require_loaded(movement)
    _validate_storage(movement)
    return AccountMovement(
        id=movement.id,
        transaction_id=movement.transaction_id,
        account_id=movement.account_id,
        direction=MovementDirection(movement.direction),
        amount=movement.amount,
        balance_after=movement.balance_after,
        category=movement.category,
        counterparty_account=movement.counterparty_account,
        counterparty_bank=movement.counterparty_bank,
        booked_at=movement.booked_at,
    )
