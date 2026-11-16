from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.account.entities import Account
from domain.transaction.entities import BankingTransaction
from domain.transaction.enums import TransactionStatus, TransactionType
from domain.transaction.exceptions import InvalidTransactionData


@pytest.fixture
def transaction() -> BankingTransaction:
    return BankingTransaction.create(
        transaction_type=TransactionType.DEPOSIT,
        amount=Decimal("120.01234567890123456789"),
        currency="CZK",
        effective_at=datetime(2024, 1, 1, 9, tzinfo=UTC),
        description="Opening deposit",
        idempotency_key="request-123",
    )


def test_valid_creation(transaction: BankingTransaction) -> None:
    assert isinstance(transaction.id, UUID) and transaction.id.version == 4
    assert transaction.transaction_type is TransactionType.DEPOSIT
    assert transaction.status is TransactionStatus.PENDING
    assert transaction.posted_at is None
    assert transaction.reversal_of_id is None
    assert transaction.amount == Decimal("120.01234567890123456789")
    assert transaction.created_at.tzinfo is UTC
    assert transaction.description == "Opening deposit"
    assert transaction.idempotency_key == "request-123"
    transaction.validate()


def test_factory_generates_identity_without_resetting_effective_time() -> None:
    values = {
        "transaction_type": TransactionType.TRANSFER,
        "amount": Decimal("1.00"),
        "currency": "EUR",
        "effective_at": datetime(2024, 1, 1, tzinfo=UTC),
    }
    before = datetime.now(UTC)
    first = BankingTransaction.create(**values)
    second = BankingTransaction.create(**values)
    assert before <= first.created_at <= second.created_at <= datetime.now(UTC)
    assert first.id != second.id
    assert first.effective_at == values["effective_at"]
    assert first.description is first.idempotency_key is None


@pytest.mark.parametrize("transaction_type", list(TransactionType))
def test_each_type_starts_pending(transaction_type: TransactionType) -> None:
    created = BankingTransaction.create(
        transaction_type=transaction_type,
        amount=Decimal("1"),
        currency="USD",
        effective_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert created.transaction_type is transaction_type
    assert created.status is TransactionStatus.PENDING


@pytest.mark.parametrize("field", ["status", "posted_at"])
def test_factory_cannot_be_used_to_post(transaction: BankingTransaction, field: str) -> None:
    values = {
        "transaction_type": transaction.transaction_type,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "effective_at": transaction.effective_at,
        field: TransactionStatus.POSTED if field == "status" else transaction.effective_at,
    }
    with pytest.raises(TypeError):
        BankingTransaction.create(**values)


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
def test_invalid_amount(transaction: BankingTransaction, amount: object) -> None:
    with pytest.raises(InvalidTransactionData, match="amount"):
        replace(transaction, amount=amount)


@pytest.mark.parametrize("amount", [Decimal("1E-100"), Decimal("1E+100"), Decimal("1.2300")])
def test_amount_preserves_precision(transaction: BankingTransaction, amount: Decimal) -> None:
    assert replace(transaction, amount=amount).amount.as_tuple() == amount.as_tuple()


@pytest.mark.parametrize("field", ["id", "reversal_of_id"])
@pytest.mark.parametrize("value", ["invalid", str(uuid4()), 123])
def test_invalid_uuid_references(
    transaction: BankingTransaction, field: str, value: object
) -> None:
    with pytest.raises(InvalidTransactionData, match=field):
        replace(transaction, **{field: value})


def test_identity_is_required(transaction: BankingTransaction) -> None:
    with pytest.raises(InvalidTransactionData, match="id"):
        replace(transaction, id=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_type", "DEPOSIT"),
        ("transaction_type", "PAYMENT"),
        ("transaction_type", None),
        ("status", "POSTED"),
        ("status", "UNKNOWN"),
        ("status", None),
    ],
)
def test_invalid_enums(transaction: BankingTransaction, field: str, value: object) -> None:
    with pytest.raises(InvalidTransactionData, match=field):
        replace(transaction, **{field: value})


@pytest.mark.parametrize(
    "currency", ["", "czk", "CZ", "EURO", " CZK", "CZK ", "CZK\n", "C1K", "ČZK", None, 123]
)
def test_currency_format(transaction: BankingTransaction, currency: object) -> None:
    with pytest.raises(InvalidTransactionData, match="currency"):
        replace(transaction, currency=currency)


@pytest.mark.parametrize("currency", ["CZK", "EUR", "USD", "ZZZ"])
def test_currency_compatible_with_accounts(transaction: BankingTransaction, currency: str) -> None:
    account = Account.create(
        customer_id=uuid4(),
        account_number="account-123",
        currency=currency,
        opened_at=date(2024, 1, 1),
    )
    assert replace(transaction, currency=currency).currency == account.currency


@pytest.mark.parametrize("status", [TransactionStatus.POSTED, TransactionStatus.REVERSED])
def test_posted_and_reversed_require_posting_time(
    transaction: BankingTransaction, status: TransactionStatus
) -> None:
    with pytest.raises(InvalidTransactionData, match="require posted_at"):
        replace(transaction, status=status)


@pytest.mark.parametrize("status", [TransactionStatus.PENDING, TransactionStatus.REJECTED])
def test_unposted_states_cannot_have_posting_time(
    transaction: BankingTransaction, status: TransactionStatus
) -> None:
    with pytest.raises(InvalidTransactionData, match="must not have posted_at"):
        replace(transaction, status=status, posted_at=transaction.effective_at)


@pytest.mark.parametrize("field", ["effective_at", "created_at", "posted_at"])
@pytest.mark.parametrize("value", ["2024-01-01T09:00:00Z", date(2024, 1, 1), 123])
def test_timestamp_types(transaction: BankingTransaction, field: str, value: object) -> None:
    with pytest.raises(InvalidTransactionData, match=field):
        replace(transaction, **{field: value})


@pytest.mark.parametrize("field", ["effective_at", "created_at"])
def test_required_timestamps(transaction: BankingTransaction, field: str) -> None:
    with pytest.raises(InvalidTransactionData, match=field):
        replace(transaction, **{field: None})


@pytest.mark.parametrize("field", ["description", "idempotency_key"])
@pytest.mark.parametrize("value", [123, [], True])
def test_optional_text_types(transaction: BankingTransaction, field: str, value: object) -> None:
    with pytest.raises(InvalidTransactionData, match=field):
        replace(transaction, **{field: value})


@pytest.mark.parametrize("status", list(TransactionStatus))
@pytest.mark.parametrize("transaction_type", list(TransactionType))
def test_reconstruction_preserves_historical_state(
    transaction: BankingTransaction, status: TransactionStatus, transaction_type: TransactionType
) -> None:
    posted_at = datetime(2024, 1, 2, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=8)))
    values = asdict(transaction)
    values.update(
        status=status,
        transaction_type=transaction_type,
        posted_at=posted_at
        if status in (TransactionStatus.POSTED, TransactionStatus.REVERSED)
        else None,
        created_at=datetime(2023, 12, 31, tzinfo=UTC),
    )
    restored = BankingTransaction(**values)
    restored.validate()
    assert asdict(restored) == values
    assert restored.id == transaction.id
    if restored.posted_at is not None:
        assert restored.posted_at.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize("status", list(TransactionStatus))
def test_all_transaction_fields_are_immutable(
    transaction: BankingTransaction, status: TransactionStatus
) -> None:
    snapshot = replace(
        transaction,
        status=status,
        posted_at=transaction.effective_at
        if status in (TransactionStatus.POSTED, TransactionStatus.REVERSED)
        else None,
    )
    before = asdict(snapshot)
    for field in before:
        with pytest.raises(FrozenInstanceError):
            setattr(snapshot, field, before[field])
    assert asdict(snapshot) == before


def test_compensation_is_a_distinct_pending_transaction(transaction: BankingTransaction) -> None:
    original = replace(
        transaction,
        status=TransactionStatus.POSTED,
        posted_at=transaction.effective_at,
        created_at=transaction.effective_at,
    )
    compensation = BankingTransaction.create(
        transaction_type=TransactionType.WITHDRAWAL,
        amount=original.amount,
        currency=original.currency,
        effective_at=original.effective_at,
        reversal_of_id=original.id,
    )
    assert compensation.id != original.id
    assert compensation.reversal_of_id == original.id
    assert compensation.status is TransactionStatus.PENDING
    assert compensation.posted_at is None
    assert original.reversal_of_id is None
    assert original.status is TransactionStatus.POSTED


def test_cannot_reference_self_as_reversal(transaction: BankingTransaction) -> None:
    with pytest.raises(InvalidTransactionData, match="cannot reference"):
        replace(transaction, reversal_of_id=transaction.id)


def test_factory_rejects_invalid_amount() -> None:
    with pytest.raises(InvalidTransactionData, match="amount"):
        BankingTransaction.create(
            transaction_type=TransactionType.DEPOSIT,
            amount=Decimal("0"),
            currency="CZK",
            effective_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
