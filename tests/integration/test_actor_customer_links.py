from uuid import uuid4

import pytest
from alembic import command
from auth_client import ActorType, CurrentActor
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from api.authentication import get_current_actor
from api.main import create_app
from infrastructure.persistence.database import create_session_factory
from infrastructure.persistence.migrate import alembic_config
from infrastructure.persistence.repositories.actor_customer_link_repository import (
    SQLAlchemyActorCustomerLinkRepository,
)
from infrastructure.settings import Settings
from ports.actor_customer_link_repository import ActorAlreadyLinked

pytestmark = pytest.mark.integration


def test_create_lookup_multiple_actors_and_remove(migrated_engine):
    sessions = create_session_factory(migrated_engine)
    actor, other, customer = uuid4(), uuid4(), uuid4()
    with sessions() as db, db.begin():
        repo = SQLAlchemyActorCustomerLinkRepository(db)
        first = repo.create_link(actor, customer)
        repo.create_link(other, customer)
    with sessions() as db, db.begin():
        repo = SQLAlchemyActorCustomerLinkRepository(db)
        assert repo.get_by_actor_id(actor) == first
        assert repo.get_by_actor_id(other).customer_id == customer
        repo.remove_link(actor)
    with sessions() as db:
        repo = SQLAlchemyActorCustomerLinkRepository(db)
        assert repo.get_by_actor_id(actor) is None
        assert repo.get_by_actor_id(other) is not None
    assert not inspect(migrated_engine).get_foreign_keys("actor_customer_links", schema="banking")


def test_duplicate_mapping_cannot_reassign_and_failed_transaction_rolls_back(migrated_engine):
    sessions = create_session_factory(migrated_engine)
    actor, customer, another = uuid4(), uuid4(), uuid4()
    with sessions() as db, db.begin():
        SQLAlchemyActorCustomerLinkRepository(db).create_link(actor, customer)
    with pytest.raises(ActorAlreadyLinked), sessions() as db, db.begin():
        SQLAlchemyActorCustomerLinkRepository(db).create_link(actor, uuid4())
    with pytest.raises(RuntimeError), sessions() as db, db.begin():
        SQLAlchemyActorCustomerLinkRepository(db).create_link(another, customer)
        raise RuntimeError("rollback")
    with sessions() as db:
        repo = SQLAlchemyActorCustomerLinkRepository(db)
        assert repo.get_by_actor_id(actor).customer_id == customer
        assert repo.get_by_actor_id(another) is None


def test_me_link_pending_removal_and_customer_denied(migrated_engine, isolated_database_settings):
    actor, customer = uuid4(), uuid4()
    app = create_app(
        Settings(
            persistence_backend="postgres",
            database_url=isolated_database_settings.database_url,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        actor, "CBS", ActorType.CUSTOMER
    )
    sessions = create_session_factory(migrated_engine)
    with TestClient(app) as client:
        assert client.get("/me").json()["link_status"] == "PENDING_LINK"
        with sessions() as db, db.begin():
            SQLAlchemyActorCustomerLinkRepository(db).create_link(actor, customer)
        assert client.get("/me").json()["customer_id"] == str(customer)
        assert client.get("/accounts").status_code == 403
        with sessions() as db, db.begin():
            SQLAlchemyActorCustomerLinkRepository(db).remove_link(actor)
        assert client.get("/me").json()["link_status"] == "PENDING_LINK"
        assert client.get("/accounts").status_code == 403


def test_link_migration_downgrade_and_upgrade(migrated_engine):
    with migrated_engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_create_transaction_requests")
        assert not inspect(connection).has_table("actor_customer_links", schema="banking")
        assert inspect(connection).has_table("accounts", schema="banking")
        command.upgrade(config, "head")
        assert inspect(connection).has_table("actor_customer_links", schema="banking")


def test_cli_link_show_remove_and_external_validation(
    migrated_engine, isolated_database_settings, capsys
):
    import json
    from unittest.mock import patch

    import link_customers

    actor, customer = uuid4(), uuid4()
    settings = Settings(
        persistence_backend="postgres",
        database_url=isolated_database_settings.database_url,
        crp_customer_service_url="https://crp.test",
        _env_file=None,
    )
    with (
        patch("link_customers.Settings", return_value=settings),
        patch("link_customers.verify_customer_actor"),
        patch("link_customers.CRPCustomerDirectory") as directory,
    ):
        directory.return_value.__enter__.return_value.exists.return_value = False
        assert (
            link_customers.main(["link", "--actor-id", str(actor), "--customer-id", str(customer)])
            == 1
        )
        assert "does not exist" in capsys.readouterr().err
        directory.return_value.__enter__.return_value.exists.return_value = True
        assert (
            link_customers.main(["link", "--actor-id", str(actor), "--customer-id", str(customer)])
            == 0
        )
        assert json.loads(capsys.readouterr().out)["customer_id"] == str(customer)
        assert (
            link_customers.main(["link", "--actor-id", str(actor), "--customer-id", str(uuid4())])
            == 1
        )
        assert "already" in capsys.readouterr().err
        assert link_customers.main(["show", "--actor-id", str(actor)]) == 0
        assert json.loads(capsys.readouterr().out)["customer_id"] == str(customer)
        assert link_customers.main(["remove", "--actor-id", str(actor)]) == 0
        capsys.readouterr()
        assert link_customers.main(["show", "--actor-id", str(actor)]) == 0
        assert json.loads(capsys.readouterr().out)["customer_id"] is None
