"""Opt-in real HTTP check; the orchestrator must provision isolated service databases."""

import os
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_single_form_registration_reaches_linked_banking_identity():
    auth = os.environ.get("REGISTRATION_AUTH_TEST_URL")
    cbs = os.environ.get("REGISTRATION_CBS_TEST_URL")
    crp = os.environ.get("REGISTRATION_CRP_TEST_URL")
    if not all((auth, cbs, crp)):
        pytest.skip("Provide isolated auth/CBS/CRP HTTP services for this end-to-end check")
    assert auth and cbs and crp
    for url in (auth, cbs, crp):
        assert url.startswith("http://127.0.0.1:")
    password = "only-test-registration-password"
    profile = {
        "birth_date": "1990-01-01",
        "employment_status": "EMPLOYED",
        "employment_months": None,
        "monthly_net_income": "2000.00",
        "monthly_housing_cost": "500.00",
        "monthly_debt_payments": "0.00",
        "monthly_basic_expenses": "300.00",
        "housing_status": "RENT",
        "country_of_residence": "ES",
        "currency": "CZK",
    }
    payload = {
        "registration_id": str(uuid4()),
        "email": f"registration-{uuid4()}@example.test",
        "password": password,
        "confirm_password": password,
        "customer_profile": profile,
    }
    with httpx.Client(timeout=20, trust_env=False) as browser:
        assert browser.get(auth + "/register").status_code == 200
        registered = browser.post(auth + "/auth/register", json=payload, headers={"Origin": auth})
        assert registered.status_code == 201 and registered.json()["link_status"] == "LINKED"
        assert "set-cookie" not in registered.headers
        assert (
            browser.post(
                auth + "/auth/register", json=payload, headers={"Origin": auth}
            ).status_code
            == 201
        )
        assert browser.post(crp + "/customers", json={}).status_code == 401
        assert (
            browser.put(cbs + f"/internal/registrations/{uuid4()}", json=profile).status_code == 404
        )
        assert (
            browser.post(
                auth + "/auth/login",
                json={"email": payload["email"], "password": password},
                headers={"Origin": auth},
            ).status_code
            == 200
        )
        authenticated = browser.get(auth + "/auth/me").json()
        assert authenticated["applications"] == [
            {"application_code": "CBS", "actor_type": "CUSTOMER"}
        ]
        me = browser.get(cbs + "/me")
        assert me.status_code == 200
        identity = me.json()
        assert identity["actor_id"] == authenticated["id"] and identity["link_status"] == "LINKED"
        customer = browser.get(crp + "/customers/" + identity["customer_id"]).json()
        assert customer["birth_date"] == profile["birth_date"]
        assert customer["monthly_net_income"] == "2000.00"
        accounts = browser.get(cbs + "/me/accounts").json()["items"]
        assert len(accounts) == 1 and accounts[0]["customer_id"] == identity["customer_id"]
        balance = browser.get(cbs + "/me/accounts/" + accounts[0]["id"] + "/balance").json()
        assert balance["booked_balance"] == "0.00"
        assert browser.post(auth + "/auth/logout", headers={"Origin": auth}).status_code == 204
        assert browser.get(auth + "/auth/me").status_code == 401
        assert browser.get(cbs + "/me").status_code == 401
