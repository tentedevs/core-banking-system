"""Test doubles only; production persistence continues to use PostgreSQL."""

from domain.account.entities import Account


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


class FakeAccountUnitOfWork:
    def __init__(self) -> None:
        self.accounts = FakeAccountRepository()
        self.commits = 0
        self.entries = 0
        self.exits = 0
        self.commit_error = None

    def __enter__(self):
        self.entries += 1
        self._before = dict(self.accounts.rows)
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


class FixedAccountNumberGenerator:
    def __init__(self, number="internal-test-account") -> None:
        self.number = number
        self.calls = 0

    def generate(self):
        self.calls += 1
        return self.number
