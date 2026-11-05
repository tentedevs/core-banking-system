from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import uuid4

from application.account_access_policy import AccountAccessPolicy
from application.account_messages import CreateAccountCommand
from application.use_cases.create_account import CreateAccount
from domain.account.entities import Account
from ports.account_unit_of_work import AccountUnitOfWork
from ports.customer_onboarding import (
    CustomerOnboarding,
    CustomerProfileRejected,
    CustomerProvisioner,
    OnboardingConflict,
)

if TYPE_CHECKING:
    from auth_client import CurrentActor


class OnboardCustomer:
    def __init__(self, work: AccountUnitOfWork, customers: CustomerProvisioner) -> None:
        self.work = work
        self.customers = customers

    def execute(self, actor: CurrentActor, profile: dict[str, object], currency: str) -> Account:
        AccountAccessPolicy.require_customer_actor(actor)
        fingerprint = hashlib.sha256(
            json.dumps(
                {"profile": profile, "currency": currency}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with self.work as work:
            work.onboardings.lock_actor(actor.actor_id)
            request = work.onboardings.get(actor.actor_id)
            if request is not None:
                if request.fingerprint != fingerprint:
                    raise OnboardingConflict("Reintenta con los mismos datos del alta original.")
                if request.account_id is not None:
                    link = work.links.get_by_actor_id_for_update(actor.actor_id)
                    if link is None or link.customer_id != request.customer_id:
                        raise OnboardingConflict(
                            "El vínculo del alta requiere revisión del operador."
                        )
                    account = work.accounts.get_by_id(request.account_id)
                    if account is None:
                        raise RuntimeError("Completed onboarding account is missing")
                    return account
            else:
                if work.links.get_by_actor_id(actor.actor_id) is not None:
                    raise OnboardingConflict("Tu perfil ya está vinculado. Actualiza la sesión.")
                request = CustomerOnboarding(actor.actor_id, uuid4(), fingerprint)
                work.onboardings.add(request)
                work.commit()
        # The stable Customer UUID is durable before any external request.
        try:
            customer_id = self.customers.ensure(request.customer_id, profile)
        except CustomerProfileRejected:
            with self.work as work:
                work.onboardings.lock_actor(actor.actor_id)
                work.onboardings.discard_rejected(actor.actor_id, request.customer_id)
                work.commit()
            raise
        if customer_id != request.customer_id:
            raise RuntimeError("Unexpected provisioned Customer identity")
        with self.work as work:
            work.onboardings.lock_actor(actor.actor_id)
            current = work.onboardings.get(actor.actor_id)
            if current is None or current.customer_id != customer_id:
                raise OnboardingConflict(
                    "El estado del alta ha cambiado. Contacta con el operador."
                )
            if current.account_id is not None:
                completed_link = work.links.get_by_actor_id_for_update(actor.actor_id)
                if completed_link is None or completed_link.customer_id != customer_id:
                    raise OnboardingConflict("El vínculo del alta requiere revisión del operador.")
                existing = work.accounts.get_by_id(current.account_id)
                if existing is None:
                    raise RuntimeError("Completed onboarding account is missing")
                return existing
            link = work.links.get_by_actor_id_for_update(actor.actor_id)
            if link is None:
                work.links.create_link(actor.actor_id, customer_id)
            elif link.customer_id != customer_id:
                raise OnboardingConflict("El usuario ya está vinculado a otro perfil.")
            account = CreateAccount(work).create_in_transaction(
                work, CreateAccountCommand(customer_id, currency)
            )
            work.onboardings.complete(actor.actor_id, account.id)
            work.commit()
            return account
