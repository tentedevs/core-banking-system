from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached

from domain.account.entities import Account
from domain.account.enums import AccountProductType, AccountStatus
from infrastructure.persistence.mappers import account_mapper
from infrastructure.persistence.models import AccountORM


@pytest.fixture
def account() -> Account:
    return Account(
        id=uuid4(),
        customer_id=uuid4(),
        account_number="0000123456",
        product_type=AccountProductType.SAVINGS_ACCOUNT,
        currency="EUR",
        status=AccountStatus.ACTIVE,
        opened_at=date(2024, 1, 1),
        created_at=datetime(2024, 1, 1, 9, 12, 3, 123456, tzinfo=UTC),
        updated_at=datetime(2024, 2, 1, 10, tzinfo=timezone(timedelta(hours=8))),
    )


def test_to_orm_preserves_every_field(account: Account) -> None:
    before = asdict(account)
    row = account_mapper.to_orm(account)
    assert {name: getattr(row, name) for name in before} == before
    assert row.product_type is AccountProductType.SAVINGS_ACCOUNT
    assert row.product_type.value == "SAVINGS_ACCOUNT"
    assert row.id is account.id
    assert row.created_at is account.created_at
    assert asdict(account) == before


@pytest.mark.parametrize("status", list(AccountStatus))
def test_round_trip_and_raw_enum_reconstruction(account: Account, status: AccountStatus) -> None:
    source = replace(
        account,
        status=status,
        closed_at=date(2024, 2, 1) if status is AccountStatus.CLOSED else None,
    )
    assert account_mapper.to_domain(account_mapper.to_orm(source)) == source
    fields = asdict(source)
    fields.update(product_type="SAVINGS_ACCOUNT", status=status.value)
    restored = account_mapper.to_domain(AccountORM(**fields))
    assert restored == source
    assert restored.status is status
    assert restored.product_type is AccountProductType.SAVINGS_ACCOUNT
    assert restored.id == source.id
    assert restored.created_at == source.created_at
    assert restored.updated_at == source.updated_at


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_mapping_rejects_naive_timestamps(account: Account, field: str) -> None:
    source = replace(account, **{field: datetime(2024, 1, 1)})
    with pytest.raises(ValueError, match=field):
        account_mapper.to_orm(source)
    row = AccountORM(**asdict(source))
    with pytest.raises(ValueError, match=field):
        account_mapper.to_domain(row)


def test_missing_fields_do_not_fall_back_to_defaults(account: Account) -> None:
    fields = asdict(account)
    del fields["status"]
    with pytest.raises(ValueError, match="all persisted fields loaded"):
        account_mapper.to_domain(AccountORM(**fields))


def test_expired_fields_are_rejected_without_sql(account: Account) -> None:
    row = account_mapper.to_orm(account)
    make_transient_to_detached(row)
    with Session() as session:
        session.add(row)
        session.expire(row)
        with pytest.raises(ValueError, match="all persisted fields loaded"):
            account_mapper.to_domain(row)


@pytest.mark.parametrize("product", ["CURRENT_ACCOUNT", "SAVING_ACCOUNT", "UNKNOWN"])
def test_unsupported_persisted_product(account: Account, product: str) -> None:
    fields = asdict(account)
    fields["product_type"] = product
    with pytest.raises(ValueError):
        account_mapper.to_domain(AccountORM(**fields))
