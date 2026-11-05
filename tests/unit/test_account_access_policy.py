from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from auth_client import ActorType, CurrentActor

from application.account_access_policy import AccountAccessPolicy, CustomerAccessDenied
from application.use_cases.get_account import AccountNotFound
from domain.customer_identity.entities import ActorCustomerLink


def test_policy_requires_customer_role_and_persisted_link():
    links, accounts, transactions = Mock(), Mock(), Mock()
    policy = AccountAccessPolicy(links, accounts, transactions)
    admin = CurrentActor(uuid4(), "CBS", ActorType.ADMIN)
    with pytest.raises(CustomerAccessDenied):
        policy.require_customer_link(admin)
    links.get_by_actor_id.return_value = None
    with pytest.raises(CustomerAccessDenied, match="Customer link required"):
        policy.require_customer_link(CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER))


def test_policy_hides_unknown_and_other_customer_accounts():
    links, accounts, transactions = Mock(), Mock(), Mock()
    actor, customer, account_id = CurrentActor(uuid4(), "CBS", ActorType.CUSTOMER), uuid4(), uuid4()
    links.get_by_actor_id.return_value = ActorCustomerLink(
        actor.actor_id, customer, datetime.now(UTC)
    )
    policy = AccountAccessPolicy(links, accounts, transactions)
    accounts.get_by_id.return_value = None
    with pytest.raises(AccountNotFound):
        policy.require_account_owner(actor, account_id)
    accounts.get_by_id.return_value = Mock(customer_id=uuid4())
    with pytest.raises(AccountNotFound):
        policy.require_account_owner(actor, account_id)
    accounts.get_by_id.return_value.customer_id = customer
    policy.require_account_owner(actor, account_id)
    transactions.has_customer_movement.return_value = True
    assert policy.can_view_transaction(actor, uuid4())
