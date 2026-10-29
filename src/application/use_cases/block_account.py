from application.account_messages import BlockAccountCommand
from application.use_cases.get_account import AccountNotFound
from domain.account.entities import Account
from ports.account_unit_of_work import AccountUnitOfWork


class BlockAccount:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, command: BlockAccountCommand) -> Account:
        with self.unit_of_work as work:
            account = work.accounts.get_by_id_for_update(command.account_id)
            if account is None:
                raise AccountNotFound(f"Account {command.account_id} not found")
            changed = account.block()
            work.accounts.save(changed)
            work.commit()
        return changed
