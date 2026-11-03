from application.transaction_messages import CreateWithdrawalCommand
from application.transaction_posting import post_operation
from domain.transaction.entities import BankingTransaction
from ports.account_unit_of_work import AccountUnitOfWork


class CreateWithdrawal:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, command: CreateWithdrawalCommand) -> BankingTransaction:
        return post_operation(self.unit_of_work, command)
