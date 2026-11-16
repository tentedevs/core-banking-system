from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from application.use_cases.read_risk_evidence import ReadRiskEvidence
from infrastructure.settings import Settings

KEY = "a" * 64
PATH = f"/internal/risk/customers/{uuid4()}/evidence"
PARAMS = {"currency": "CZK", "start": "2026-08-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"}
HEADERS = {"Authorization": f"Bearer {KEY}", "X-Service-ID": "crp-backend"}


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 401),
        ({**HEADERS, "Origin": "https://evil"}, 403),
        ({**HEADERS, "X-Service-ID": "other"}, 401),
    ],
)
def test_internal_evidence_authentication(headers, status):
    app = create_app(Settings(_env_file=None, risk_service_credential=KEY), internal=True)
    with TestClient(app) as client:
        assert client.get(PATH, params=PARAMS, headers=headers).status_code == status


def test_evidence_is_not_published_on_public_listener():
    with TestClient(create_app(Settings(_env_file=None, risk_service_credential=KEY))) as client:
        assert client.get(PATH, params=PARAMS, headers=HEADERS).status_code == 404


def test_authorized_evidence_uses_only_customer_scope(monkeypatch):
    from api.dependencies import get_session

    app = create_app(Settings(_env_file=None, risk_service_credential=KEY), internal=True)
    app.dependency_overrides[get_session] = lambda: Mock()
    query = Mock()
    query.page.return_value = {"customer_id": PATH.split("/")[-2]}
    monkeypatch.setattr("api.routers.risk_evidence.SQLAlchemyRiskEvidenceQuery", lambda _: query)
    with TestClient(app) as client:
        response = client.get(PATH, params=PARAMS, headers=HEADERS)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert str(query.page.call_args.args[0]) == PATH.split("/")[-2]
        assert query.page.call_args.args[1] == "CZK"


def test_invalid_window_never_queries_database():
    query = Mock()
    with pytest.raises(ValueError):
        ReadRiskEvidence(query).execute(
            uuid4(),
            "CZK",
            datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 8, 1, tzinfo=UTC),
            100,
            0,
        )
    query.page.assert_not_called()
