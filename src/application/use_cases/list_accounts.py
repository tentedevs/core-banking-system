from application.account_messages import ListAccountsQuery
from domain.account.entities import Account
from ports.account_repository import AccountRepository
from ports.account_unit_of_work import AccountUnitOfWork


class ListAccounts:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: ListAccountsQuery) -> list[Account]:
        with self.unit_of_work as work:
            return self._items(work.accounts, query)

    def execute_with_total(self, query: ListAccountsQuery) -> tuple[list[Account], int]:
        with self.unit_of_work as work:
            return self._items(work.accounts, query), work.accounts.count(query.customer_id)

    @staticmethod
    def _items(repository: AccountRepository, query: ListAccountsQuery) -> list[Account]:
        if query.customer_id is not None:
            return repository.list_by_customer(
                query.customer_id, limit=query.limit, offset=query.offset
            )
        return repository.list_all(limit=query.limit, offset=query.offset)
