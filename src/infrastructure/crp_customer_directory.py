from types import TracebackType
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ports.customer_directory import CustomerDirectoryUnavailable


class CRPCustomerDirectory:
    """Read-only adapter to CRP's existing GET /customers/{id} contract."""

    def __init__(
        self,
        base_url: str,
        *,
        allow_insecure_http: bool = False,
        timeout: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
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
            raise ValueError("CRP must use an HTTPS origin; trusted HTTP requires explicit opt-in")
        if not 0 < timeout <= 10:
            raise ValueError("CRP timeout must be between 0 and 10 seconds")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=min(timeout, 0.5)),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def exists(self, customer_id: UUID) -> bool:
        try:
            with self.client.stream("GET", f"/customers/{customer_id}") as response:
                if response.status_code == 404:
                    return False
                if (
                    response.status_code != 200
                    or response.headers.get("content-type", "").split(";")[0] != "application/json"
                ):
                    raise CustomerDirectoryUnavailable("Customer directory unavailable")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise CustomerDirectoryUnavailable("Customer directory unavailable")
                import json

                data = json.loads(content)
                if not isinstance(data, dict) or data.get("id") != str(customer_id):
                    raise CustomerDirectoryUnavailable("Invalid customer directory response")
                return True
        except (httpx.HTTPError, ValueError, RecursionError):
            pass
        raise CustomerDirectoryUnavailable("Customer directory unavailable")

    def __enter__(self) -> "CRPCustomerDirectory":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.client.close()
