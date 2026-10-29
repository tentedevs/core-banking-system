import pytest

from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from infrastructure.persistence.database import create_session_factory

pytestmark = pytest.mark.integration


@pytest.fixture
def work(migrated_engine):
    return SQLAlchemyAccountUnitOfWork(create_session_factory(migrated_engine))


def test_unit_of_work_requires_context_and_rejects_nested_entry(work):
    with pytest.raises(RuntimeError, match="entered"):
        work.commit()
    with pytest.raises(RuntimeError, match="entered"):
        _ = work.accounts
    with work:
        with pytest.raises(RuntimeError, match="already active"):
            with work:
                pytest.fail("Nested transaction should be rejected")
    with pytest.raises(RuntimeError, match="entered"):
        _ = work.accounts
