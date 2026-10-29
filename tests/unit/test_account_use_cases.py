from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from application.account_messages import (
    BlockAccountCommand,
    CreateAccountCommand,
    GetAccountByNumberQuery,
    GetAccountQuery,
    ListAccountsQuery,
    ReactivateAccountCommand,
)
from application.account_numbers import InternalAccountNumberGenerator
from application.use_cases.block_account import BlockAccount
from application.use_cases.create_account import CreateAccount
from application.use_cases.get_account import AccountNotFound, GetAccount
from application.use_cases.get_account_by_number import GetAccountByNumber
from application.use_cases.list_accounts import ListAccounts
from application.use_cases.reactivate_account import ReactivateAccount
from domain.account.entities import Account
from domain.account.enums import AccountProductType, AccountStatus
from domain.account.exceptions import InvalidAccountData, InvalidAccountStateTransition
from ports.account_repository import AccountNumberConflict
from tests.account_fakes import FakeAccountUnitOfWork, FixedAccountNumberGenerator


@pytest.fixture
def work():
    return FakeAccountUnitOfWork()


@pytest.fixture
def account(work):
    account = Account.create(
        customer_id=uuid4(),
        account_number="existing-number",
        currency="CZK",
        opened_at=date(2024, 1, 1),
    )
    work.accounts.rows[account.id] = account
    return account


def test_create_defaults_and_commits(work):
    generator = FixedAccountNumberGenerator()
    customer_id = uuid4()
    before = datetime.now(UTC)
    account = CreateAccount(work, generator).execute(CreateAccountCommand(customer_id))
    after = datetime.now(UTC)
    assert isinstance(account.id, UUID) and account.id.version == 4
    assert account.customer_id == customer_id
    assert account.currency == "CZK"
    assert account.product_type is AccountProductType.SAVINGS_ACCOUNT
    assert account.status is AccountStatus.ACTIVE and account.closed_at is None
    assert before.date() <= account.opened_at <= after.date()
    assert before <= account.created_at == account.updated_at <= after
    assert account.created_at.tzinfo is UTC
    assert account.account_number == generator.number
    assert work.accounts.rows[account.id] == account
    assert work.commits == work.entries == work.exits == 1


def test_create_generates_distinct_internal_numbers_and_ids(work):
    create = CreateAccount(work)
    first = create.execute(CreateAccountCommand(uuid4(), currency="EUR"))
    second = create.execute(CreateAccountCommand(first.customer_id))
    assert first.id != second.id
    assert first.account_number != second.account_number
    assert first.currency == "EUR"
    for number in (first.account_number, second.account_number):
        assert number.startswith("C") and len(number) == 33
        UUID(hex=number[1:])


@pytest.mark.parametrize("currency", ["", "czk", "CZ", "EURO", "ÉUR", None])
def test_create_validates_through_domain_before_writing(work, currency):
    with pytest.raises(InvalidAccountData, match="currency"):
        CreateAccount(work).execute(CreateAccountCommand(uuid4(), currency=currency))
    assert work.accounts.rows == {}
    assert work.entries == work.commits == 0


def test_generator_output_is_domain_validated(work):
    with pytest.raises(InvalidAccountData, match="account_number"):
        CreateAccount(work, FixedAccountNumberGenerator("")).execute(CreateAccountCommand(uuid4()))
    assert work.commits == 0


def test_collision_is_not_retried(work):
    work.commit_error = AccountNumberConflict("duplicate number")
    generator = FixedAccountNumberGenerator()
    with pytest.raises(AccountNumberConflict):
        CreateAccount(work, generator).execute(CreateAccountCommand(uuid4()))
    assert generator.calls == 1
    assert work.accounts.rows == {}
    assert work.exits == 1


def test_get_operations_are_read_only(work, account):
    before = asdict(account)
    assert GetAccount(work).execute(GetAccountQuery(account.id)) is account
    assert (
        GetAccountByNumber(work).execute(GetAccountByNumberQuery(account.account_number)) is account
    )
    assert work.commits == 0
    assert work.entries == work.exits == 2
    assert asdict(account) == before
    assert [call[0] for call in work.accounts.calls] == ["get_by_id", "get_by_account_number"]


@pytest.mark.parametrize("operation", ["get", "number", "block", "reactivate"])
def test_missing_accounts_raise_consistent_application_error(work, operation):
    actions = {
        "get": lambda: GetAccount(work).execute(GetAccountQuery(uuid4())),
        "number": lambda: GetAccountByNumber(work).execute(GetAccountByNumberQuery("unknown")),
        "block": lambda: BlockAccount(work).execute(BlockAccountCommand(uuid4())),
        "reactivate": lambda: ReactivateAccount(work).execute(ReactivateAccountCommand(uuid4())),
    }
    with pytest.raises(AccountNotFound):
        actions[operation]()
    assert work.commits == 0 and work.exits == 1


def test_list_routes_filter_and_pagination_to_repository(work, account):
    ordered = [replace(account, id=UUID(int=i), account_number=f"n-{i}") for i in range(1, 4)]
    other = replace(account, id=UUID(int=4), account_number="other", customer_id=uuid4())
    work.accounts.rows = {row.id: row for row in reversed(ordered + [other])}
    listing = ListAccounts(work)
    assert listing.execute(ListAccountsQuery(limit=2, offset=1)) == ordered[1:3]
    assert work.accounts.calls[-1] == ("list_all", 2, 1)
    assert listing.execute(ListAccountsQuery(account.customer_id, limit=1, offset=1)) == [
        ordered[1]
    ]
    assert work.accounts.calls[-1] == ("list_by_customer", account.customer_id, 1, 1)
    assert listing.execute(ListAccountsQuery(uuid4())) == []
    assert work.commits == 0


def test_block_and_reactivate_use_locked_domain_transitions(work, account):
    blocked = BlockAccount(work).execute(BlockAccountCommand(account.id))
    assert blocked.status is AccountStatus.BLOCKED
    assert work.accounts.rows[account.id] == blocked
    assert work.accounts.calls[0] == ("get_by_id_for_update", account.id)
    active = ReactivateAccount(work).execute(ReactivateAccountCommand(account.id))
    assert active.status is AccountStatus.ACTIVE
    assert work.accounts.rows[account.id] == active
    assert work.commits == 2
    for name in (
        "id",
        "customer_id",
        "account_number",
        "product_type",
        "currency",
        "opened_at",
        "created_at",
    ):
        assert getattr(active, name) == getattr(account, name)
    assert account.status is AccountStatus.ACTIVE


@pytest.mark.parametrize(
    ("status", "operation"),
    [
        (AccountStatus.BLOCKED, "block"),
        (AccountStatus.ACTIVE, "reactivate"),
        (AccountStatus.CLOSED, "block"),
        (AccountStatus.CLOSED, "reactivate"),
    ],
)
def test_invalid_transitions_do_not_save_or_commit(work, account, status, operation):
    historical = replace(
        account,
        status=status,
        closed_at=account.opened_at if status is AccountStatus.CLOSED else None,
    )
    work.accounts.rows[account.id] = historical
    with pytest.raises(InvalidAccountStateTransition):
        if operation == "block":
            BlockAccount(work).execute(BlockAccountCommand(account.id))
        else:
            ReactivateAccount(work).execute(ReactivateAccountCommand(account.id))
    assert work.accounts.rows[account.id] == historical
    assert all(call[0] != "save" for call in work.accounts.calls)
    assert work.commits == 0


def test_failed_commit_rolls_back_status_and_propagates(work, account):
    work.commit_error = RuntimeError("database failure")
    with pytest.raises(RuntimeError, match="database failure"):
        BlockAccount(work).execute(BlockAccountCommand(account.id))
    assert work.accounts.rows[account.id] == account
    assert work.exits == 1


@pytest.mark.parametrize(
    "message",
    [CreateAccountCommand, GetAccountQuery, BlockAccountCommand, ReactivateAccountCommand],
)
@pytest.mark.parametrize("value", [None, "not-a-uuid", str(uuid4())])
def test_commands_and_queries_validate_uuids(message, value):
    with pytest.raises(ValueError, match="UUID"):
        message(value)


@pytest.mark.parametrize("number", [None, "", " \t", 123])
def test_account_number_query_requires_nonblank_string(number):
    with pytest.raises(ValueError, match="account_number"):
        GetAccountByNumberQuery(number)


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"limit": True}, "limit"),
        ({"limit": None}, "limit"),
        ({"limit": 1.5}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": True}, "offset"),
        ({"offset": None}, "offset"),
        ({"offset": 0.5}, "offset"),
        ({"customer_id": "invalid"}, "customer_id"),
    ],
)
def test_list_query_validates_before_transaction(work, values, field):
    with pytest.raises(ValueError, match=field):
        ListAccounts(work).execute(ListAccountsQuery(**values))
    assert work.entries == 0


def test_internal_number_generator_has_no_external_dependencies():
    number = InternalAccountNumberGenerator().generate()
    assert number[0] == "C"
    assert len(number) <= 34
    assert UUID(hex=number[1:]).version == 4
