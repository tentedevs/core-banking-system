from application.transaction_messages import ListTransactionMovementsQuery
from application.use_cases.get_transaction import TransactionNotFound
from domain.transaction.entities import AccountMovement
from ports.account_unit_of_work import AccountUnitOfWork


class ListTransactionMovements:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute_with_total(
        self, query: ListTransactionMovementsQuery
    ) -> tuple[list[AccountMovement], int]:
        with self.unit_of_work as work:
            if work.transactions.get_by_id(query.transaction_id) is None:
                raise TransactionNotFound(f"Transaction {query.transaction_id} not found")
            items = work.movements.list_by_transaction(
                query.transaction_id, query.limit, query.offset
            )
            return items, work.movements.count_by_transaction(query.transaction_id)
