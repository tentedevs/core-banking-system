from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from infrastructure.persistence.repositories.account_repository import SQLAlchemyAccountRepository
from ports.account_repository import AccountRepository


@pytest.mark.parametrize("method", ["list_all", "list_by_customer"])
@pytest.mark.parametrize(
    ("arguments", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": -1}, "limit"),
        ({"limit": 101}, "limit"),
        ({"limit": True}, "limit"),
        ({"limit": 1.5}, "limit"),
        ({"limit": None}, "limit"),
        ({"limit": "50"}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": True}, "offset"),
        ({"offset": 1.5}, "offset"),
        ({"offset": None}, "offset"),
        ({"offset": "0"}, "offset"),
    ],
)
def test_invalid_pagination_fails_before_database_access(method, arguments, field) -> None:
    # No bound engine: attempting SQL would fail instead of giving a pagination error.
    with Session() as session:
        repository: AccountRepository = SQLAlchemyAccountRepository(session)
        query = getattr(repository, method)
        positional = (uuid4(),) if method == "list_by_customer" else ()
        with pytest.raises(ValueError, match=field):
            query(*positional, **arguments)
