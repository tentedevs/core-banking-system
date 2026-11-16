from typing import Protocol
from uuid import UUID


class CustomerDirectoryUnavailable(RuntimeError):
    pass


class CustomerNotFound(ValueError):
    pass


class CustomerDirectory(Protocol):
    def exists(self, customer_id: UUID) -> bool: ...
