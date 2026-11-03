from alembic.script import ScriptDirectory

from infrastructure.persistence.migrate import alembic_config
from infrastructure.persistence.models import Base


def test_migration_configuration_registers_accounts() -> None:
    config = alembic_config()
    assert ScriptDirectory.from_config(config).get_heads() == ["0004_create_transaction_requests"]
    assert set(Base.metadata.tables) == {
        "banking.accounts",
        "banking.transactions",
        "banking.account_movements",
        "banking.account_balances",
        "banking.account_balance_openings",
        "banking.transaction_requests",
    }
