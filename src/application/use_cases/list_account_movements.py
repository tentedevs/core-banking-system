from application.transaction_messages import ListAccountMovementsQuery
from application.use_cases.get_account import AccountNotFound
from domain.transaction.entities import AccountMovement
from ports.account_unit_of_work import AccountUnitOfWork


class ListAccountMovements:
    def __init__(self, unit_of_work: AccountUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def execute(self, query: ListAccountMovementsQuery) -> list[AccountMovement]:
        with self.unit_of_work as work:
            if work.accounts.get_by_id(query.account_id) is None:
                raise AccountNotFound(f"Account {query.account_id} not found")
            return work.movements.list_by_account(
                query.account_id, limit=query.limit, offset=query.offset
            )

    def execute_with_total(
        self, query: ListAccountMovementsQuery
    ) -> tuple[list[AccountMovement], int]:
        with self.unit_of_work as work:
            if work.accounts.get_by_id(query.account_id) is None:
                raise AccountNotFound(f"Account {query.account_id} not found")
            items = work.movements.list_by_account(
                query.account_id, limit=query.limit, offset=query.offset
            )
            return items, work.movements.count_by_account(query.account_id)
