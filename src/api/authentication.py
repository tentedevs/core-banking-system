from collections.abc import Callable
from typing import Annotated, cast

from auth_client import ActorType, CurrentActor
from fastapi import Depends, HTTPException, Request


def get_current_actor(request: Request) -> CurrentActor:
    dependency = cast(
        Callable[[Request], CurrentActor] | None, request.app.state.current_actor_dependency
    )
    if dependency is None:
        if not request.cookies.get(request.app.state.settings.auth_session_cookie_name):
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    return dependency(request)


def require_banking_admin(
    request: Request, actor: Annotated[CurrentActor, Depends(get_current_actor)]
) -> None:
    if actor.actor_type is not ActorType.ADMIN:
        raise HTTPException(status_code=403, detail="Administrative access required")
    validate_banking_request_origin(request)


def validate_banking_request_origin(request: Request) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origins = request.headers.getlist("origin")
        if (
            len(origins) > 1
            or (origins and origins[0] not in request.app.state.settings.banking_trusted_origins)
            or request.headers.get("sec-fetch-site") == "cross-site"
            or (not origins and any(key.startswith("sec-fetch-") for key in request.headers))
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
