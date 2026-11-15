from __future__ import annotations

from typing import TYPE_CHECKING

from application.account_access_policy import AccountAccessPolicy
from application.account_messages import CreateAccountCommand
from application.use_cases.create_account import CreateAccount
from domain.account.entities import Account
from ports.account_opening_repository import CustomerAccountOpening
from ports.account_unit_of_work import AccountUnitOfWork
from ports.customer_onboarding import CustomerOnboardingGateway, OnboardingConflict

if TYPE_CHECKING:
    from auth_client import CurrentActor


class OnboardCustomer:
    """Compatibility coordinator: Customer Service owns identity; CBS opens accounts.

    The remote step finishes before the local banking transaction starts. Retrying
    a failed local step reuses the Customer and the unique account-opening receipt.
    """

    def __init__(self, work: AccountUnitOfWork, customers: CustomerOnboardingGateway) -> None:
        self.work, self.customers = work, customers

    def execute(
        self,
        actor: CurrentActor,
        profile: dict[str, object],
        currency: str,
        session_token: str | None = None,
    ) -> Account:
        AccountAccessPolicy.require_customer_actor(actor)
        customer_id = self.customers.onboard(actor.actor_id, profile, currency, session_token)
        with self.work as work:
            work.account_openings.lock_customer(customer_id)
            receipt = work.account_openings.get(customer_id)
            if receipt is not None:
                if receipt.currency != currency:
                    raise OnboardingConflict("Account opening already uses another currency")
                account = work.accounts.get_by_id(receipt.account_id)
                if account is None or account.customer_id != customer_id:
                    raise OnboardingConflict("Account opening requires operator review")
                return account
            account = CreateAccount(work).create_in_transaction(
                work, CreateAccountCommand(customer_id, currency)
            )
            work.account_openings.add(CustomerAccountOpening(customer_id, account.id, currency))
            work.commit()
            return account
