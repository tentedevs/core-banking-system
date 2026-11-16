from application.transaction_messages import ListTransactionsQuery
from domain.transaction.entities import BankingTransaction
from ports.account_unit_of_work import AccountUnitOfWork


class ListTransactions:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: ListTransactionsQuery) -> list[BankingTransaction]:
        with self.unit_of_work as work:
            return work.transactions.list_all(
                limit=query.limit,
                offset=query.offset,
                transaction_type=query.transaction_type,
                status=query.status,
            )

    def execute_with_total(
        self, query: ListTransactionsQuery
    ) -> tuple[list[BankingTransaction], int]:
        with self.unit_of_work as work:
            items = work.transactions.list_all(
                limit=query.limit,
                offset=query.offset,
                transaction_type=query.transaction_type,
                status=query.status,
            )
            total = work.transactions.count(
                transaction_type=query.transaction_type, status=query.status
            )
            return items, total
