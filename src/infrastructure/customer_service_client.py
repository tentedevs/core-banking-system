"""Single bounded HTTP transport for Customer Service adapters."""

import json
from types import TracebackType
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ports.customer_directory import CustomerDirectoryUnavailable
from ports.customer_identity import CustomerIdentityUnavailable
from ports.customer_onboarding import (
    CustomerProfileRejected,
    CustomerProvisioningUnavailable,
    OnboardingConflict,
)


class CustomerServiceClient:
    def __init__(
        self,
        base_url: str,
        credential: str,
        *,
        service_id: str = "cbs-backend",
        allow_insecure_http: bool = False,
        timeout: float = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        import re

        parts = urlsplit(base_url)
        if (
            not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
            or parts.scheme not in {"https", "http"}
            or (parts.scheme == "http" and not allow_insecure_http)
        ):
            raise ValueError("Customer Service requires an HTTPS origin or explicit trusted HTTP")
        if re.fullmatch(r"[0-9a-f]{64}", credential) is None:
            raise ValueError("Customer Service credential must be 64 lowercase hex characters")
        if re.fullmatch(r"[a-z][a-z0-9-]{0,49}", service_id) is None or not 0 < timeout <= 30:
            raise ValueError("Invalid Customer Service client configuration")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {credential}", "X-Service-ID": service_id},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 1), pool=min(timeout, 1)),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        try:
            with self.client.stream(method, path, json=payload) as response:
                status = response.status_code
                if status in {404, 409, 422}:
                    return status, {}
                if (
                    status != 200
                    or response.headers.get("content-type", "").split(";")[0] != "application/json"
                ):
                    raise CustomerIdentityUnavailable("Customer Service unavailable")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise CustomerIdentityUnavailable("Invalid Customer Service response")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError
                return status, result
        except (httpx.HTTPError, ValueError, RecursionError):
            raise CustomerIdentityUnavailable("Customer Service unavailable") from None

    def resolve_customer_id(self, actor_id: UUID) -> UUID | None:
        status, body = self._request("GET", f"/internal/v1/actors/{actor_id}/customer")
        try:
            if status != 200 or body.get("actor_id") != str(actor_id):
                raise ValueError
            if body.get("status") == "PENDING_LINK" and body.get("customer_id") is None:
                return None
            if body.get("status") != "LINKED" or not isinstance(body.get("customer_id"), str):
                raise ValueError
            return UUID(str(body["customer_id"]))
        except (ValueError, TypeError):
            raise CustomerIdentityUnavailable("Invalid identity response") from None

    def exists(self, customer_id: UUID) -> bool:
        try:
            status, body = self._request("GET", f"/internal/v1/customers/{customer_id}")
            if status == 404:
                return False
            if status != 200 or body.get("customer_id") != str(customer_id):
                raise CustomerIdentityUnavailable("Invalid Customer response")
            return True
        except CustomerIdentityUnavailable:
            raise CustomerDirectoryUnavailable("Customer Service unavailable") from None

    def onboard(
        self,
        actor_id: UUID,
        profile: dict[str, object],
        currency: str,
        session_token: str | None = None,
    ) -> UUID:
        payload = {**profile, "actor_id": str(actor_id), "currency": currency}
        if session_token is not None:
            payload["session_token"] = session_token
        try:
            status, body = self._request("POST", "/internal/v1/customers/onboarding", payload)
            if status == 409:
                raise OnboardingConflict("Retry with original data or contact the operator")
            if status == 422:
                raise CustomerProfileRejected("Invalid Customer profile")
            if (
                status != 200
                or body.get("actor_id") != str(actor_id)
                or body.get("status") != "LINKED"
                or not isinstance(body.get("customer_id"), str)
            ):
                raise ValueError
            return UUID(str(body["customer_id"]))
        except (CustomerProfileRejected, OnboardingConflict):
            raise
        except (CustomerIdentityUnavailable, ValueError, TypeError):
            raise CustomerProvisioningUnavailable("Customer onboarding unavailable") from None

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "CustomerServiceClient":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
