from application.account_messages import GetAccountByNumberQuery
from application.use_cases.get_account import AccountNotFound
from domain.account.entities import Account
from ports.account_unit_of_work import AccountUnitOfWork


class GetAccountByNumber:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: GetAccountByNumberQuery) -> Account:
        with self.unit_of_work as work:
            account = work.accounts.get_by_account_number(query.account_number)
            if account is None:
                raise AccountNotFound(f"Account {query.account_number} not found")
            return account
