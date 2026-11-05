from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class OnboardingConflict(ValueError):
    pass


class CustomerProvisioningUnavailable(RuntimeError):
    pass


class CustomerProfileRejected(ValueError):
    pass


@dataclass(frozen=True)
class CustomerOnboarding:
    actor_id: UUID
    customer_id: UUID
    fingerprint: str
    account_id: UUID | None = None


class CustomerOnboardingRepository(Protocol):
    def lock_actor(self, actor_id: UUID) -> None: ...
    def get(self, actor_id: UUID) -> CustomerOnboarding | None: ...
    def add(self, request: CustomerOnboarding) -> None: ...
    def complete(self, actor_id: UUID, account_id: UUID) -> None: ...
    def discard_rejected(self, actor_id: UUID, customer_id: UUID) -> None: ...


class CustomerProvisioner(Protocol):
    def ensure(self, customer_id: UUID, profile: dict[str, object]) -> UUID: ...
