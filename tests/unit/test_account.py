from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from domain.account.entities import Account
from domain.account.enums import AccountProductType, AccountStatus
from domain.account.exceptions import InvalidAccountData, InvalidAccountStateTransition


@pytest.fixture
def account() -> Account:
    return Account.create(
        customer_id=uuid4(),
        account_number="0000123456",
        product_type=AccountProductType.SAVINGS_ACCOUNT,
        currency="EUR",
        opened_at=date(2024, 1, 1),
    )


def test_valid_account_creation(account: Account) -> None:
    assert isinstance(account.id, UUID)
    assert isinstance(account.customer_id, UUID)
    assert account.account_number == "0000123456"
    assert account.product_type is AccountProductType.SAVINGS_ACCOUNT
    assert account.currency == "EUR"
    assert account.opened_at == date(2024, 1, 1)
    assert account.created_at == account.updated_at
    assert account.created_at.tzinfo is UTC
    account.validate()


def test_creation_defaults_to_active(account: Account) -> None:
    assert account.status is AccountStatus.ACTIVE
    assert account.closed_at is None


@pytest.mark.parametrize("field", ["id", "customer_id"])
@pytest.mark.parametrize("value", [None, "not-a-uuid", str(uuid4()), 123])
def test_invalid_identity(account: Account, field: str, value: object) -> None:
    with pytest.raises(InvalidAccountData, match=field):
        replace(account, **{field: value})


@pytest.mark.parametrize("number", ["", " ", "\t\n", None, 123])
def test_invalid_account_number(account: Account, number: object) -> None:
    with pytest.raises(InvalidAccountData, match="account_number"):
        replace(account, account_number=number)


@pytest.mark.parametrize(
    "currency", ["", "eu", "EURO", "eur", "Eur", " EU", "EUR ", "EUR\n", "E1R", "ÉUR", None, 123]
)
def test_invalid_currency_format(account: Account, currency: object) -> None:
    with pytest.raises(InvalidAccountData, match="currency"):
        replace(account, currency=currency)


@pytest.mark.parametrize("currency", ["EUR", "USD", "MYR", "ZZZ"])
def test_currency_checks_format_only(account: Account, currency: str) -> None:
    # Membership in the ISO registry is intentionally deferred.
    assert replace(account, currency=currency).currency == currency


def test_factory_validates_data(account: Account) -> None:
    with pytest.raises(InvalidAccountData, match="account_number"):
        Account.create(
            customer_id=account.customer_id,
            account_number="",
            product_type=account.product_type,
            currency=account.currency,
            opened_at=account.opened_at,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_type", "SAVINGS_ACCOUNT"),
        ("product_type", "CURRENT_ACCOUNT"),
        ("product_type", "SAVING_ACCOUNT"),
        ("product_type", None),
        ("status", "ACTIVE"),
        ("status", "UNKNOWN"),
        ("status", None),
    ],
)
def test_invalid_enum_data(account: Account, field: str, value: object) -> None:
    with pytest.raises(InvalidAccountData, match=field):
        replace(account, **{field: value})


def test_block_active_account(account: Account) -> None:
    before = datetime.now(UTC)
    blocked = account.block()
    after = datetime.now(UTC)
    assert blocked.status is AccountStatus.BLOCKED
    assert before <= blocked.updated_at <= after
    assert account.status is AccountStatus.ACTIVE
    assert blocked.closed_at is None


def test_reactivate_blocked_account(account: Account) -> None:
    blocked = account.block()
    before = datetime.now(UTC)
    active = blocked.reactivate()
    after = datetime.now(UTC)
    assert active.status is AccountStatus.ACTIVE
    assert before <= active.updated_at <= after
    assert active.updated_at.tzinfo is UTC
    assert blocked.status is AccountStatus.BLOCKED
    assert active.closed_at is None


@pytest.mark.parametrize(
    ("status", "operation"),
    [
        (AccountStatus.BLOCKED, "block"),
        (AccountStatus.ACTIVE, "reactivate"),
        (AccountStatus.CLOSED, "block"),
        (AccountStatus.CLOSED, "reactivate"),
    ],
)
def test_invalid_state_transitions(account: Account, status: AccountStatus, operation: str) -> None:
    historical = replace(
        account,
        status=status,
        closed_at=date(2024, 2, 1) if status is AccountStatus.CLOSED else None,
    )
    before = asdict(historical)
    with pytest.raises(InvalidAccountStateTransition, match=operation):
        getattr(historical, operation)()
    assert asdict(historical) == before


def test_closed_account_requires_closing_date(account: Account) -> None:
    with pytest.raises(InvalidAccountData, match="must have closed_at"):
        replace(account, status=AccountStatus.CLOSED)


def test_closing_date_cannot_precede_opening_date(account: Account) -> None:
    with pytest.raises(InvalidAccountData, match="cannot precede opened_at"):
        replace(account, status=AccountStatus.CLOSED, closed_at=date(2023, 12, 31))


@pytest.mark.parametrize("closed_at", [date(2024, 1, 1), date(2024, 2, 1)])
def test_valid_closed_dates(account: Account, closed_at: date) -> None:
    historical = replace(account, status=AccountStatus.CLOSED, closed_at=closed_at)
    assert historical.closed_at == closed_at


@pytest.mark.parametrize("status", [AccountStatus.ACTIVE, AccountStatus.BLOCKED])
def test_non_closed_account_cannot_have_closing_date(
    account: Account, status: AccountStatus
) -> None:
    with pytest.raises(InvalidAccountData, match="only a CLOSED account"):
        replace(account, status=status, closed_at=date(2024, 2, 1))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("opened_at", None),
        ("opened_at", "2024-01-01"),
        ("opened_at", datetime(2024, 1, 1, tzinfo=UTC)),
        ("closed_at", "2024-02-01"),
        ("closed_at", datetime(2024, 2, 1, tzinfo=UTC)),
        ("created_at", None),
        ("created_at", date(2024, 1, 1)),
        ("updated_at", "2024-01-01T00:00:00Z"),
    ],
)
def test_invalid_date_and_timestamp_types(account: Account, field: str, value: object) -> None:
    with pytest.raises(InvalidAccountData, match=field):
        replace(account, **{field: value})


@pytest.mark.parametrize("status", list(AccountStatus))
def test_reconstruction_preserves_historical_fields(
    account: Account, status: AccountStatus
) -> None:
    fields = asdict(account)
    fields.update(
        status=status,
        created_at=datetime(2024, 1, 1, 10, tzinfo=UTC),
        updated_at=datetime(2024, 2, 1, 12, tzinfo=UTC),
        closed_at=date(2024, 2, 1) if status is AccountStatus.CLOSED else None,
    )
    historical = Account(**fields)
    historical.validate()
    assert asdict(historical) == fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_type", "OTHER"),
        ("currency", "USD"),
        ("status", AccountStatus.CLOSED),
        ("closed_at", date(2024, 2, 1)),
    ],
)
def test_direct_assignment_is_forbidden(account: Account, field: str, value: object) -> None:
    before = asdict(account)
    with pytest.raises(FrozenInstanceError):
        setattr(account, field, value)
    assert asdict(account) == before


def test_transitions_preserve_account_attributes(account: Account) -> None:
    for snapshot in (account.block(), account.block().reactivate()):
        for field in (
            "id",
            "customer_id",
            "account_number",
            "product_type",
            "currency",
            "opened_at",
            "created_at",
        ):
            assert getattr(snapshot, field) == getattr(account, field)


def test_creation_defaults_to_savings_product(account: Account) -> None:
    created = Account.create(
        customer_id=account.customer_id,
        account_number=account.account_number,
        currency=account.currency,
        opened_at=account.opened_at,
    )
    assert created.product_type is AccountProductType.SAVINGS_ACCOUNT


@pytest.mark.parametrize("value", ["CURRENT_ACCOUNT", "SAVING_ACCOUNT"])
def test_unsupported_product_enum(value: str) -> None:
    with pytest.raises(ValueError):
        AccountProductType(value)
