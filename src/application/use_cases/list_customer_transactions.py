from uuid import UUID

from application.transaction_messages import ListTransactionsQuery
from domain.transaction.entities import BankingTransaction
from ports.transaction_repository import TransactionRepository


class ListCustomerTransactions:
    def __init__(self, transactions: TransactionRepository) -> None:
        self.transactions = transactions

    def execute_with_total(
        self, customer_id: UUID, query: ListTransactionsQuery
    ) -> tuple[list[BankingTransaction], int]:
        items = self.transactions.list_by_customer(
            customer_id,
            query.limit,
            query.offset,
            transaction_type=query.transaction_type,
            status=query.status,
        )
        total = self.transactions.count_by_customer(
            customer_id,
            transaction_type=query.transaction_type,
            status=query.status,
        )
        return items, total
