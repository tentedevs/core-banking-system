from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached

from domain.transaction.enums import MovementDirection, TransactionStatus, TransactionType
from infrastructure.persistence.mappers import account_movement_mapper, transaction_mapper
from infrastructure.persistence.models import AccountMovementORM, TransactionORM
from tests.transaction_factories import movement, transaction


@pytest.mark.parametrize("kind", list(TransactionType))
@pytest.mark.parametrize("status", list(TransactionStatus))
def test_transaction_round_trip_preserves_every_field(kind, status):
    source = transaction()
    source = replace(
        source,
        transaction_type=kind,
        status=status,
        posted_at=source.posted_at
        if status in (TransactionStatus.POSTED, TransactionStatus.REVERSED)
        else None,
        reversal_of_id=uuid4(),
    )
    before = asdict(source)
    row = transaction_mapper.to_orm(source)
    assert {name: getattr(row, name) for name in before} == before
    assert transaction_mapper.to_domain(row) == source
    assert row.amount is source.amount
    raw = dict(before, transaction_type=kind.value, status=status.value)
    assert transaction_mapper.to_domain(TransactionORM(**raw)) == source
    assert asdict(source) == before


@pytest.mark.parametrize("direction", list(MovementDirection))
@pytest.mark.parametrize("nullable", [True, False])
def test_movement_round_trip_preserves_fields(direction, nullable):
    source = replace(movement(uuid4(), uuid4()), direction=direction)
    if nullable:
        source = replace(
            source,
            balance_after=None,
            category=None,
            counterparty_account=None,
            counterparty_bank=None,
        )
    before = asdict(source)
    row = account_movement_mapper.to_orm(source)
    assert {name: getattr(row, name) for name in before} == before
    assert account_movement_mapper.to_domain(row) == source
    assert (
        account_movement_mapper.to_domain(
            AccountMovementORM(**dict(before, direction=direction.value))
        )
        == source
    )
    assert asdict(source) == before


def test_transaction_nullable_fields_are_preserved():
    source = replace(
        transaction(),
        status=TransactionStatus.PENDING,
        description=None,
        posted_at=None,
        idempotency_key=None,
    )
    assert transaction_mapper.to_domain(transaction_mapper.to_orm(source)) == source


@pytest.mark.parametrize("entity", ["transaction", "movement"])
@pytest.mark.parametrize(
    "amount",
    [Decimal("0.001"), Decimal("1.234"), Decimal("10000000000000000.00"), Decimal("1E-100")],
)
def test_money_is_not_silently_rounded_or_overflowed(entity, amount):
    source, mapper = (
        (transaction(), transaction_mapper)
        if entity == "transaction"
        else (movement(uuid4(), uuid4()), account_movement_mapper)
    )
    source = replace(source, amount=amount)
    with pytest.raises(ValueError, match="NUMERIC"):
        mapper.to_orm(source)


@pytest.mark.parametrize(
    "balance", [Decimal("-0.001"), Decimal("-10000000000000000"), Decimal("NaN")]
)
def test_movement_storage_validation_also_checks_balance(balance):
    row = AccountMovementORM(**dict(asdict(movement(uuid4(), uuid4())), balance_after=balance))
    with pytest.raises(ValueError, match="balance_after"):
        account_movement_mapper.to_domain(row)


@pytest.mark.parametrize(
    "amount", [Decimal("0.01"), Decimal("9999999999999999.99"), Decimal("1.2300")]
)
def test_exact_money_does_not_depend_on_decimal_context(amount):
    source = replace(transaction(), amount=amount)
    with localcontext() as context:
        context.prec = 2
        assert transaction_mapper.to_orm(source).amount.as_tuple() == amount.as_tuple()


@pytest.mark.parametrize("field", ["created_at", "effective_at", "posted_at"])
def test_transaction_requires_aware_datetimes(field):
    source = replace(transaction(), **{field: datetime(2024, 1, 1)})
    with pytest.raises(ValueError, match=field):
        transaction_mapper.to_orm(source)
    with pytest.raises(ValueError, match=field):
        transaction_mapper.to_domain(TransactionORM(**asdict(source)))


def test_movement_requires_aware_datetime():
    source = replace(movement(uuid4(), uuid4()), booked_at=datetime(2024, 1, 1))
    with pytest.raises(ValueError, match="booked_at"):
        account_movement_mapper.to_orm(source)
    with pytest.raises(ValueError, match="booked_at"):
        account_movement_mapper.to_domain(AccountMovementORM(**asdict(source)))


@pytest.mark.parametrize("entity", ["transaction", "movement"])
def test_unloaded_and_expired_fields_are_rejected_without_sql(entity):
    mapper, cls, source = (
        (transaction_mapper, TransactionORM, transaction())
        if entity == "transaction"
        else (account_movement_mapper, AccountMovementORM, movement(uuid4(), uuid4()))
    )
    fields = asdict(source)
    del fields["amount"]
    with pytest.raises(ValueError, match="all persisted fields loaded"):
        mapper.to_domain(cls(**fields))
    row = mapper.to_orm(source)
    make_transient_to_detached(row)
    with Session() as session:
        session.add(row)
        session.expire(row)
        with pytest.raises(ValueError, match="all persisted fields loaded"):
            mapper.to_domain(row)
