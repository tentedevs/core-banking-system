"""Deprecated identity CLI: show resolves via HTTP; mutations belong to Customer Service."""

import argparse
import getpass
import json
import os
import sys
import warnings
from typing import Never
from uuid import UUID

from auth_client import ActorType, AuthServiceClient
from pydantic import ValidationError

from infrastructure.settings import Settings


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
    """Deprecated mutation CLI: identity writes belong to Customer Service."""
    from infrastructure.customer_service_client import CustomerServiceClient
    from ports.customer_identity import CustomerIdentityUnavailable

    try:
        args = parser().parse_args(argv)
        if args.operation != "show":
            raise LinkingInputError(
                "Identity mutations moved to Customer Service; use its audited administrative API."
            )
        settings = Settings()
        if not settings.customer_service_url or not settings.customer_service_credential:
            raise LinkingInputError("Configure Customer Service before resolving identities")
        with CustomerServiceClient(
            settings.customer_service_url,
            settings.customer_service_credential.get_secret_value(),
            service_id=settings.customer_service_id,
            allow_insecure_http=settings.customer_service_allow_insecure_http,
            timeout=settings.customer_service_request_timeout,
        ) as client:
            customer_id = client.resolve_customer_id(args.actor_id)
        print(
            json.dumps(
                {
                    "actor_id": str(args.actor_id),
                    "customer_id": str(customer_id) if customer_id else None,
                }
            )
        )
        return 0
    except (LinkingInputError, CustomerIdentityUnavailable) as error:
        print(str(error), file=sys.stderr)
    except (ValidationError, ValueError):
        print("Invalid Customer Service configuration.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
