from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from auth_client import ActorType, CurrentActor

from infrastructure.settings import Settings
from link_customers import LinkingInputError, main, verify_customer_actor


@pytest.mark.parametrize(
    "role,matches,allowed",
    [
        (ActorType.CUSTOMER, True, True),
        (ActorType.CUSTOMER, False, False),
        (ActorType.ADMIN, True, False),
    ],
)
def test_cli_verifies_target_actor_and_cbs_role(monkeypatch, role, matches, allowed):
    actor = uuid4()
    settings = Settings(
        auth_service_internal_url="https://auth.test",
        auth_service_credential="a" * 64,
        _env_file=None,
    )
    monkeypatch.setenv("CBS_LINK_TEST_SESSION", "private-session")
    client = MagicMock()
    client.__enter__.return_value.resolve.return_value = CurrentActor(
        actor if matches else uuid4(), "CBS", role
    )
    with patch("link_customers.AuthServiceClient", return_value=client):
        if allowed:
            verify_customer_actor(settings, actor, "CBS_LINK_TEST_SESSION")
        else:
            with pytest.raises(LinkingInputError):
                verify_customer_actor(settings, actor, "CBS_LINK_TEST_SESSION")
    client.__enter__.return_value.resolve.assert_called_once_with("private-session")
    import os

    assert "CBS_LINK_TEST_SESSION" not in os.environ


def test_cli_requires_explicit_database_and_does_not_echo_bad_arguments(capsys):
    with patch("link_customers.Settings", return_value=Settings(_env_file=None)):
        assert main(["show", "--actor-id", str(uuid4())]) == 1
    assert main(["--unrecognized", "secret-value"]) == 1
    assert "secret-value" not in capsys.readouterr().err


def test_cli_refuses_unverified_target(monkeypatch):
    settings = Settings(
        auth_service_internal_url="https://auth.test",
        auth_service_credential="a" * 64,
        _env_file=None,
    )
    monkeypatch.delenv("CBS_LINK_TEST_SESSION", raising=False)
    with pytest.raises(LinkingInputError):
        verify_customer_actor(settings, uuid4(), "CBS_LINK_TEST_SESSION")
