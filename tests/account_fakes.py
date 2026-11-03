"""Test doubles only; production persistence continues to use PostgreSQL."""

from decimal import Decimal

from domain.account.entities import Account
from domain.account_balance.entities import AccountBalance, BalanceOpening
from domain.account_balance.enums import BalanceInitializationPolicy
from ports.balance_repository import BalanceAlreadyInitialized, PostedMovementSummary


class FakeAccountRepository:
    def __init__(self) -> None:
        self.rows = {}
        self.calls = []

    def save(self, account: Account) -> None:
        self.calls.append(("save", account))
        self.rows[account.id] = account

    def get_by_id(self, account_id):
        self.calls.append(("get_by_id", account_id))
        return self.rows.get(account_id)

    def get_by_id_for_update(self, account_id):
        self.calls.append(("get_by_id_for_update", account_id))
        return self.rows.get(account_id)

    def get_by_account_number(self, number):
        self.calls.append(("get_by_account_number", number))
        return next((row for row in self.rows.values() if row.account_number == number), None)

    def list_all(self, limit=50, offset=0):
        self.calls.append(("list_all", limit, offset))
        return sorted(self.rows.values(), key=lambda row: row.id)[offset : offset + limit]

    def list_by_customer(self, customer_id, limit=50, offset=0):
        self.calls.append(("list_by_customer", customer_id, limit, offset))
        rows = sorted(
            (row for row in self.rows.values() if row.customer_id == customer_id),
            key=lambda row: row.id,
        )
        return rows[offset : offset + limit]

    def count(self, customer_id=None):
        self.calls.append(("count", customer_id))
        return sum(
            1 for row in self.rows.values() if customer_id is None or row.customer_id == customer_id
        )


class FakeBalanceRepository:
    def __init__(self):
        self.rows = {}
        self.openings = {}
        self.summaries = {}
        self.calls = []

    def get_by_account_id(self, account_id):
        return self.rows.get(account_id)

    def create_initial_balance(
        self,
        account_id,
        initial_balance=Decimal("0"),
        *,
        policy=BalanceInitializationPolicy.ORDINARY,
    ):
        if account_id in self.rows:
            raise BalanceAlreadyInitialized("Account balance is already initialized")
        balance = AccountBalance.create_initial(account_id, initial_balance, policy=policy)
        self.rows[account_id] = balance
        self.openings[account_id] = BalanceOpening(
            account_id, initial_balance, policy, balance.updated_at
        )
        return balance

    def get_for_update(self, account_id):
        self.calls.append(account_id)
        return self.rows.get(account_id)

    def persist_updated_balance(self, balance):
        self.rows[balance.account_id] = balance

    def get_opening(self, account_id):
        return self.openings.get(account_id)

    def get_posted_movement_summary(self, account_id, currency):
        return self.summaries.get(account_id, PostedMovementSummary(Decimal("0"), 0))


class FakeAccountUnitOfWork:
    def __init__(self) -> None:
        self.accounts = FakeAccountRepository()
        self.balances = FakeBalanceRepository()
        self.commits = 0
        self.entries = 0
        self.exits = 0
        self.commit_error = None

    def __enter__(self):
        self.entries += 1
        self._before = dict(self.accounts.rows)
        self._balances_before = dict(self.balances.rows)
        self._openings_before = dict(self.balances.openings)
        self._committed = False
        return self

    def commit(self):
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1
        self._committed = True

    def __exit__(self, exc_type, exc_value, traceback):
        self.exits += 1
        if not self._committed:
            self.accounts.rows = self._before
            self.balances.rows = self._balances_before
            self.balances.openings = self._openings_before


class FixedAccountNumberGenerator:
    def __init__(self, number="internal-test-account") -> None:
        self.number = number
        self.calls = 0

    def generate(self):
        self.calls += 1
        return self.number
