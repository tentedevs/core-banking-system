from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Iterator[Session | None]:
    factory = cast(sessionmaker[Session] | None, request.app.state.session_factory)
    if factory is None:
        yield None
        return
    with factory() as session:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            # Close the read transaction without committing writes.
            yield session
        else:
            with session.begin():
                yield session


# Commit/rollback and close BEFORE sending the response, including commit failures.
SessionDependency = Annotated[Session | None, Depends(get_session, scope="function")]
