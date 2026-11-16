from datetime import datetime
from typing import Protocol
from uuid import UUID


class RiskEvidenceQuery(Protocol):
    def page(
        self,
        customer_id: UUID,
        currency: str,
        start: datetime,
        end: datetime,
        limit: int,
        offset: int,
    ) -> dict[str, object]: ...
