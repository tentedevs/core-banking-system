from datetime import UTC, datetime

from application.account_messages import CreateAccountCommand
from application.account_numbers import InternalAccountNumberGenerator
from domain.account.entities import Account
from ports.account_number_generator import AccountNumberGenerator
from ports.account_unit_of_work import AccountUnitOfWork


class CreateAccount:
    def __init__(
        self,
        unit_of_work: AccountUnitOfWork,
        number_generator: AccountNumberGenerator | None = None,
    ) -> None:
        self.unit_of_work = unit_of_work
        self.number_generator = (
            number_generator if number_generator is not None else InternalAccountNumberGenerator()
        )

    def execute(self, command: CreateAccountCommand) -> Account:
        account = Account.create(
            customer_id=command.customer_id,
            currency=command.currency,
            account_number=self.number_generator.generate(),
            opened_at=datetime.now(UTC).date(),
        )
        with self.unit_of_work as work:
            work.accounts.save(account)
            work.commit()
        return account
