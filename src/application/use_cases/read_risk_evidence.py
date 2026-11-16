from datetime import datetime
from uuid import UUID

from ports.risk_evidence import RiskEvidenceQuery


class ReadRiskEvidence:
    def __init__(self, query: RiskEvidenceQuery) -> None:
        self.query = query

    def execute(
        self,
        customer_id: UUID,
        currency: str,
        start: datetime,
        end: datetime,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        if start >= end or (end - start).days > 366:
            raise ValueError("Invalid evidence window")
        return self.query.page(customer_id, currency, start, end, limit, offset)
