"""Operator-only customer links; run on a host with CBS database credentials."""

import argparse
import getpass
import json
import os
import sys
import warnings
from typing import Never
from uuid import UUID

from auth_client import ActorType, AuthServiceClient
from auth_client.exceptions import AccessDenied, AuthenticationRequired, AuthServiceUnavailable
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from application.customer_identity import LinkActorToCustomer
from infrastructure.crp_customer_directory import CRPCustomerDirectory
from infrastructure.persistence.database import create_database_engine, create_session_factory
from infrastructure.persistence.repositories.actor_customer_link_repository import (
    SQLAlchemyActorCustomerLinkRepository,
)
from infrastructure.settings import Settings
from ports.actor_customer_link_repository import ActorAlreadyLinked
from ports.customer_directory import CustomerDirectoryUnavailable, CustomerNotFound


class LinkingInputError(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise LinkingInputError("Invalid linking arguments; use --help")


def parser() -> argparse.ArgumentParser:
    result = SafeParser(description=__doc__)
    sub = result.add_subparsers(dest="operation", required=True)
    for operation in ("link", "show", "remove"):
        command = sub.add_parser(operation)
        command.add_argument("--actor-id", type=UUID, required=True)
        if operation == "link":
            command.add_argument("--customer-id", type=UUID, required=True)
            command.add_argument("--actor-session-env", help="Protected environment variable name")
    return result


def verify_customer_actor(settings: Settings, actor_id: UUID, token_variable: str | None) -> None:
    if not settings.auth_service_internal_url or not settings.auth_service_credential:
        raise LinkingInputError("Configure auth service integration before linking")
    if token_variable:
        import re

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_variable) is None:
            raise LinkingInputError("Invalid session environment variable name")
        token = os.environ.pop(token_variable, "")
    else:
        if not sys.stdin.isatty():
            raise LinkingInputError("Use a secure terminal or --actor-session-env")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                token = getpass.getpass("Target actor session (hidden): ")
        except getpass.GetPassWarning:
            raise LinkingInputError("Secure terminal input unavailable") from None
    if not token:
        raise LinkingInputError("A target actor session is required")
    with AuthServiceClient(
        base_url=settings.auth_service_internal_url,
        service_id=settings.auth_service_id,
        service_credential=settings.auth_service_credential.get_secret_value(),
        application_code=settings.auth_application_code,
        timeout=settings.auth_request_timeout,
        allow_insecure_http=settings.auth_allow_insecure_http,
    ) as client:
        actor = client.resolve(token)
    if actor.actor_id != actor_id or actor.actor_type is not ActorType.CUSTOMER:
        raise LinkingInputError("The verified session must belong to the target CBS CUSTOMER")


def main(argv: list[str] | None = None) -> int:
    engine = None
    try:
        args = parser().parse_args(argv)
        settings = Settings()
        if settings.persistence_backend != "postgres":
            raise LinkingInputError("Link management requires CBS PostgreSQL persistence")
        if args.operation == "link":
            verify_customer_actor(settings, args.actor_id, args.actor_session_env)
            if not settings.crp_customer_service_url:
                raise LinkingInputError("Configure CRP_CUSTOMER_SERVICE_URL before linking")
        engine = create_database_engine(settings)
        output: dict[str, object]
        with create_session_factory(engine)() as session, session.begin():
            links = SQLAlchemyActorCustomerLinkRepository(session)
            if args.operation == "link":
                with CRPCustomerDirectory(
                    settings.crp_customer_service_url or "",
                    allow_insecure_http=settings.crp_customer_allow_insecure_http,
                    timeout=settings.crp_customer_request_timeout,
                ) as customers:
                    link = LinkActorToCustomer(links, customers).execute(
                        args.actor_id, args.customer_id
                    )
                output = {"actor_id": str(link.actor_id), "customer_id": str(link.customer_id)}
            elif args.operation == "show":
                existing = links.get_by_actor_id(args.actor_id)
                output = {
                    "actor_id": str(args.actor_id),
                    "customer_id": str(existing.customer_id) if existing else None,
                }
            else:
                links.remove_link(args.actor_id)
                output = {"actor_id": str(args.actor_id), "removed": True}
        print(json.dumps(output))
        return 0
    except (
        ValidationError,
        SQLAlchemyError,
        AuthenticationRequired,
        AccessDenied,
        AuthServiceUnavailable,
        CustomerDirectoryUnavailable,
    ):
        print("Link operation failed; check service and database configuration.", file=sys.stderr)
    except (LinkingInputError, CustomerNotFound, ActorAlreadyLinked) as error:
        print(str(error), file=sys.stderr)
    except ValueError:
        print("Invalid linking configuration.", file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
