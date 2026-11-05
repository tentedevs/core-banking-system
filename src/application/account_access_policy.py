from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from application.use_cases.get_account import AccountNotFound
from ports.account_repository import AccountRepository
from ports.actor_customer_link_repository import ActorCustomerLinkRepository
from ports.transaction_repository import TransactionRepository

if TYPE_CHECKING:
    from auth_client import CurrentActor


class CustomerAccessDenied(Exception):
    pass


class AccountAccessPolicy:
    def __init__(
        self,
        links: ActorCustomerLinkRepository,
        accounts: AccountRepository,
        transactions: TransactionRepository,
    ) -> None:
        self.links = links
        self.accounts = accounts
        self.transactions = transactions

    @staticmethod
    def require_customer_actor(actor: CurrentActor) -> None:
        if actor.application_code != "CBS" or actor.actor_type != "CUSTOMER":
            raise CustomerAccessDenied("CBS CUSTOMER access required")

    def require_customer_link(self, actor: CurrentActor) -> UUID:
        self.require_customer_actor(actor)
        link = self.links.get_by_actor_id(actor.actor_id)
        if link is None:
            raise CustomerAccessDenied("Customer link required")
        return link.customer_id

    def require_account_owner(self, actor: CurrentActor, account_id: UUID) -> None:
        customer = self.require_customer_link(actor)
        account = self.accounts.get_by_id(account_id)
        if account is None or account.customer_id != customer:
            raise AccountNotFound("Account not found")

    def can_view_transaction(self, actor: CurrentActor, transaction_id: UUID) -> bool:
        customer = self.require_customer_link(actor)
        return self.transactions.has_customer_movement(transaction_id, customer)
