from datetime import UTC, datetime

from application.account_balance_service import AccountBalanceService
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
        account = self._build(command)
        with self.unit_of_work as work:
            self._persist(work, account)
            work.commit()
            return account

    def _build(self, command: CreateAccountCommand) -> Account:
        return Account.create(
            customer_id=command.customer_id,
            currency=command.currency,
            account_number=self.number_generator.generate(),
            opened_at=datetime.now(UTC).date(),
        )

    @staticmethod
    def _persist(work: AccountUnitOfWork, account: Account) -> None:
        work.accounts.save(account)
        AccountBalanceService(work.accounts, work.balances).initialize(
            account.id, currency=account.currency
        )

    def create_in_transaction(
        self, work: AccountUnitOfWork, command: CreateAccountCommand
    ) -> Account:
        """Reuse account creation inside a larger caller-owned CBS transaction."""
        account = self._build(command)
        self._persist(work, account)
        return account
