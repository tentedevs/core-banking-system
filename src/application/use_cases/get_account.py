from application.account_messages import GetAccountQuery
from domain.account.entities import Account
from ports.account_unit_of_work import AccountUnitOfWork


class AccountNotFound(Exception):
    pass


class GetAccount:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: GetAccountQuery) -> Account:
        with self.unit_of_work as work:
            account = work.accounts.get_by_id(query.account_id)
            if account is None:
                raise AccountNotFound(f"Account {query.account_id} not found")
            return account
