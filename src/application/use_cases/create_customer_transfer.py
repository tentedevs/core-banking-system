from __future__ import annotations

from typing import TYPE_CHECKING

from application.account_access_policy import AccountAccessPolicy, CustomerAccessDenied
from application.transaction_messages import CreateTransferCommand
from application.use_cases.create_transfer import CreateTransfer
from application.use_cases.get_account import AccountNotFound
from domain.transaction.entities import BankingTransaction
from ports.account_unit_of_work import AccountUnitOfWork

if TYPE_CHECKING:
    from auth_client import CurrentActor


class CreateCustomerTransfer:
    """Authorize within the existing posting transaction; never implement posting here."""

    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, actor: CurrentActor, command: CreateTransferCommand) -> BankingTransaction:
        AccountAccessPolicy.require_customer_actor(actor)

        def authorize(work: AccountUnitOfWork) -> None:
            if work.links.get_by_actor_id_for_update(actor.actor_id) is None:
                raise CustomerAccessDenied("Customer link required")
            policy = AccountAccessPolicy(work.links, work.accounts, work.transactions)
            # Conceal a foreign source before looking up any destination details.
            policy.require_account_owner(actor, command.source_account_id)
            # Match posting's deterministic account lock order. Ownership and
            # account status cannot change between the final check and commit.
            ids = (command.source_account_id, command.destination_account_id)
            for account_id in sorted(ids, key=lambda value: value.int):
                if work.accounts.get_by_id_for_update(account_id) is None:
                    raise AccountNotFound("Account not found")
            policy.require_account_owner(actor, command.source_account_id)

        return CreateTransfer(self.unit_of_work, authorize=authorize).execute(command)
