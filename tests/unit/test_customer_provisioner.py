from uuid import uuid4

import httpx
import pytest

from infrastructure.crp_customer_provisioner import CRPCustomerProvisioner
from ports.customer_onboarding import (
    CustomerProfileRejected,
    CustomerProvisioningUnavailable,
    OnboardingConflict,
)

KEY = "b" * 64


@pytest.mark.parametrize(
    "status,error",
    [
        (401, CustomerProvisioningUnavailable),
        (403, CustomerProvisioningUnavailable),
        (404, CustomerProvisioningUnavailable),
        (409, OnboardingConflict),
        (422, CustomerProfileRejected),
        (503, CustomerProvisioningUnavailable),
    ],
)
def test_upstream_statuses_fail_without_exposing_details(status, error):
    with CRPCustomerProvisioner(
        "https://crp.test",
        KEY,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"detail": "private-internal-detail"})
        ),
    ) as client:
        with pytest.raises(error) as result:
            client.ensure(uuid4(), {})
    assert "private-internal-detail" not in str(result.value) and KEY not in str(result.value)


def test_provisioner_uses_private_service_credentials_and_stable_customer_id():
    customer_id = uuid4()

    def respond(request):
        assert (
            request.method == "PUT"
            and request.url.path == f"/internal/customer-provisioning/{customer_id}"
        )
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.headers["x-service-id"] == "cbs-onboarding"
        assert "cookie" not in request.headers
        return httpx.Response(200, json={"id": str(customer_id)})

    with CRPCustomerProvisioner(
        "https://crp.test", KEY, transport=httpx.MockTransport(respond)
    ) as client:
        assert client.ensure(customer_id, {"country_of_residence": "ES"}) == customer_id


def test_bad_identity_or_network_never_completes_onboarding():
    def timeout(request):
        raise httpx.ReadTimeout("private-credential")

    for handler in (timeout, lambda request: httpx.Response(200, json={"id": str(uuid4())})):
        with CRPCustomerProvisioner(
            "https://crp.test", KEY, transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(CustomerProvisioningUnavailable):
                client.ensure(uuid4(), {})
