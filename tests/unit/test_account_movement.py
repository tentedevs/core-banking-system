from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.transaction.entities import AccountMovement, BankingTransaction
from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from domain.transaction.exceptions import InvalidAccountMovementData


@pytest.fixture
def movement() -> AccountMovement:
    return AccountMovement.create(
        transaction_id=uuid4(),
        account_id=uuid4(),
        direction=MovementDirection.CREDIT,
        amount=Decimal("10.123456789"),
        booked_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_valid_creation(movement: AccountMovement) -> None:
    assert isinstance(movement.id, UUID) and movement.id.version == 4
    assert movement.amount == Decimal("10.123456789")
    assert movement.direction is MovementDirection.CREDIT
    assert movement.balance_after is None
    assert movement.category is movement.counterparty_account is movement.counterparty_bank is None
    assert movement.booked_at == datetime(2024, 1, 1, tzinfo=UTC)
    movement.validate()


@pytest.mark.parametrize("direction", list(MovementDirection))
def test_credit_and_debit_both_use_positive_amounts(
    movement: AccountMovement, direction: MovementDirection
) -> None:
    restored = replace(movement, direction=direction)
    assert restored.direction is direction
    assert restored.amount == movement.amount


@pytest.mark.parametrize("direction", ["CREDIT", "DEBIT", "UNKNOWN", 1, None])
def test_invalid_direction(movement: AccountMovement, direction: object) -> None:
    with pytest.raises(InvalidAccountMovementData, match="direction"):
        replace(movement, direction=direction)


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        1,
        1.5,
        "1.50",
        True,
        None,
    ],
)
def test_invalid_amount(movement: AccountMovement, amount: object) -> None:
    with pytest.raises(InvalidAccountMovementData, match="amount"):
        replace(movement, amount=amount)


@pytest.mark.parametrize("field", ["id", "transaction_id", "account_id"])
@pytest.mark.parametrize("value", ["invalid", str(uuid4()), None, 123])
def test_uuid_references(movement: AccountMovement, field: str, value: object) -> None:
    with pytest.raises(InvalidAccountMovementData, match=field):
        replace(movement, **{field: value})


@pytest.mark.parametrize(
    "balance", [None, Decimal("-123.4500"), Decimal("0"), Decimal("12.34"), Decimal("-1E+100")]
)
def test_balance_after_can_be_negative_or_absent(
    movement: AccountMovement, balance: Decimal | None
) -> None:
    restored = replace(movement, balance_after=balance)
    assert restored.balance_after == balance
    if balance is not None:
        assert restored.balance_after is not None
        assert restored.balance_after.as_tuple() == balance.as_tuple()


@pytest.mark.parametrize(
    "balance",
    [
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        1,
        1.5,
        "12.34",
        True,
    ],
)
def test_balance_after_requires_finite_decimal(movement: AccountMovement, balance: object) -> None:
    with pytest.raises(InvalidAccountMovementData, match="balance_after"):
        replace(movement, balance_after=balance)


@pytest.mark.parametrize("amount", [Decimal("1E-100"), Decimal("1E+100"), Decimal("1.2300")])
def test_amount_precision(movement: AccountMovement, amount: Decimal) -> None:
    assert replace(movement, amount=amount).amount.as_tuple() == amount.as_tuple()


@pytest.mark.parametrize("value", [None, "2024-01-01T00:00:00Z", date(2024, 1, 1), 123])
def test_booked_at_type(movement: AccountMovement, value: object) -> None:
    with pytest.raises(InvalidAccountMovementData, match="booked_at"):
        replace(movement, booked_at=value)


@pytest.mark.parametrize("field", ["category", "counterparty_account", "counterparty_bank"])
@pytest.mark.parametrize("value", [123, [], True])
def test_optional_text_types(movement: AccountMovement, field: str, value: object) -> None:
    with pytest.raises(InvalidAccountMovementData, match=field):
        replace(movement, **{field: value})


def test_complete_historical_reconstruction(movement: AccountMovement) -> None:
    values = asdict(movement)
    values.update(
        direction=MovementDirection.DEBIT,
        balance_after=Decimal("-25.0001"),
        category="normalized-category",
        counterparty_account="000-12345",
        counterparty_bank="Example bank",
        booked_at=datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=8))),
    )
    restored = AccountMovement(**values)
    restored.validate()
    assert asdict(restored) == values
    assert restored.id == movement.id
    assert restored.transaction_id == movement.transaction_id
    assert restored.account_id == movement.account_id
    assert restored.booked_at.utcoffset() == timedelta(hours=8)


def test_movement_is_immutable(movement: AccountMovement) -> None:
    before = asdict(movement)
    for field in before:
        with pytest.raises(FrozenInstanceError):
            setattr(movement, field, before[field])
    assert asdict(movement) == before


def test_factory_rejects_invalid_reference() -> None:
    with pytest.raises(InvalidAccountMovementData, match="transaction_id"):
        AccountMovement.create(
            transaction_id="not-a-uuid",  # type: ignore[arg-type]
            account_id=uuid4(),
            direction=MovementDirection.CREDIT,
            amount=Decimal("10"),
            booked_at=datetime(2024, 1, 1, tzinfo=UTC),
        )


def test_internal_transfer_references_one_transaction_without_constructor_cardinalities() -> None:
    booked_at = datetime(2024, 1, 1, tzinfo=UTC)
    transaction = BankingTransaction(
        id=uuid4(),
        transaction_type=TransactionType.TRANSFER,
        status=TransactionStatus.POSTED,
        amount=Decimal("10.00"),
        currency="CZK",
        effective_at=booked_at,
        posted_at=booked_at,
        created_at=booked_at,
    )
    source, target = uuid4(), uuid4()
    movements = [
        AccountMovement.create(
            transaction_id=transaction.id,
            account_id=account_id,
            direction=direction,
            amount=transaction.amount,
            booked_at=booked_at,
        )
        for account_id, direction in (
            (source, MovementDirection.DEBIT),
            (target, MovementDirection.CREDIT),
        )
    ]
    assert movements[0].id != movements[1].id
    assert all(item.transaction_id == transaction.id for item in movements)
    assert movements[0].account_id == source and movements[1].account_id == target
    assert asdict(transaction)["amount"] == Decimal("10.00")
