from application.transaction_messages import GetAccountBalanceQuery
from application.use_cases.get_account import AccountNotFound
from domain.account_balance.entities import AccountBalance
from ports.account_unit_of_work import AccountUnitOfWork
from ports.balance_repository import BalanceNotFound


class GetAccountBalance:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: GetAccountBalanceQuery) -> AccountBalance:
        with self.unit_of_work as work:
            if work.accounts.get_by_id(query.account_id) is None:
                raise AccountNotFound(f"Account {query.account_id} not found")
            balance = work.balances.get_by_account_id(query.account_id)
            if balance is None:
                raise BalanceNotFound(f"Balance for account {query.account_id} is not initialized")
            return balance
