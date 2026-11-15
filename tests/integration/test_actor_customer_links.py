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


def test_local_legacy_links_do_not_authorize_requests(migrated_engine, isolated_database_settings):
    from unittest.mock import Mock

    from api.dependencies import get_customer_identity

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
    identities = Mock()
    identities.resolve_customer_id.return_value = None
    app.dependency_overrides[get_customer_identity] = lambda: identities
    sessions = create_session_factory(migrated_engine)
    with sessions() as db, db.begin():
        SQLAlchemyActorCustomerLinkRepository(db).create_link(actor, customer)
    with TestClient(app) as client:
        assert client.get("/me").json()["link_status"] == "PENDING_LINK"
        assert client.get("/me/accounts").status_code == 403
        assert client.get("/accounts").status_code == 403
        identities.resolve_customer_id.return_value = customer
        assert client.get("/me").json()["customer_id"] == str(customer)


def test_link_migration_downgrade_and_upgrade(migrated_engine):
    with migrated_engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_create_transaction_requests")
        assert not inspect(connection).has_table("actor_customer_links", schema="banking")
        assert inspect(connection).has_table("accounts", schema="banking")
        command.upgrade(config, "head")
        assert inspect(connection).has_table("actor_customer_links", schema="banking")


def test_cli_cannot_mutate_legacy_identity_tables(migrated_engine, capsys):
    from sqlalchemy import func, select

    import link_customers
    from infrastructure.persistence.models import ActorCustomerLinkORM

    actor, customer = uuid4(), uuid4()
    assert (
        link_customers.main(["link", "--actor-id", str(actor), "--customer-id", str(customer)]) == 1
    )
    assert link_customers.main(["remove", "--actor-id", str(actor)]) == 1
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ActorCustomerLinkORM)) == 0
    assert "Customer Service" in capsys.readouterr().err
