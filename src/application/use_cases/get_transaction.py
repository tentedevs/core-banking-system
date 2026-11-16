from application.transaction_messages import GetTransactionQuery
from domain.transaction.entities import BankingTransaction
from ports.account_unit_of_work import AccountUnitOfWork


class TransactionNotFound(Exception):
    pass


class GetTransaction:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: GetTransactionQuery) -> BankingTransaction:
        with self.unit_of_work as work:
            transaction = work.transactions.get_by_id(query.transaction_id)
            if transaction is None:
                raise TransactionNotFound(f"Transaction {query.transaction_id} not found")
            return transaction
