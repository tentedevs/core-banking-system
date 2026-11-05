import json
from types import TracebackType
from uuid import UUID

import httpx

from infrastructure.crp_customer_directory import CRPCustomerDirectory
from ports.customer_onboarding import (
    CustomerProfileRejected,
    CustomerProvisioningUnavailable,
    OnboardingConflict,
)


class CRPCustomerProvisioner:
    def __init__(
        self,
        base_url: str,
        credential: str,
        *,
        allow_insecure_http: bool = False,
        timeout: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        import re

        if re.fullmatch(r"[0-9a-f]{64}", credential) is None:
            raise ValueError("Provisioning credential must be 64 lowercase hex characters")
        self._credential = credential
        self._directory = CRPCustomerDirectory(
            base_url, allow_insecure_http=allow_insecure_http, timeout=timeout, transport=transport
        )

    def ensure(self, customer_id: UUID, profile: dict[str, object]) -> UUID:
        try:
            with self._directory.client.stream(
                "PUT",
                f"/internal/customer-provisioning/{customer_id}",
                headers={
                    "Authorization": f"Bearer {self._credential}",
                    "X-Service-ID": "cbs-onboarding",
                },
                json=profile,
            ) as response:
                if response.status_code == 422:
                    raise CustomerProfileRejected("Revisa los datos del perfil bancario.")
                if response.status_code == 409:
                    raise OnboardingConflict(
                        "El perfil ya existe con otros datos. Contacta con el operador."
                    )
                if (
                    response.status_code not in {200, 201}
                    or response.headers.get("content-type", "").split(";")[0] != "application/json"
                ):
                    raise CustomerProvisioningUnavailable(
                        "No se puede completar el alta. Reintenta con los mismos datos."
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise CustomerProvisioningUnavailable("Respuesta de CRP no válida.")
                result = json.loads(content)
                if not isinstance(result, dict) or result.get("id") != str(customer_id):
                    raise CustomerProvisioningUnavailable("Respuesta de CRP no válida.")
                return customer_id
        except (CustomerProfileRejected, OnboardingConflict):
            raise
        except (httpx.HTTPError, ValueError, RecursionError):
            pass
        raise CustomerProvisioningUnavailable(
            "No se puede confirmar el alta. Reintenta con los mismos datos."
        )

    def __enter__(self) -> "CRPCustomerProvisioner":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._directory.client.close()
