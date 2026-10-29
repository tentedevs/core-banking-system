from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from application.account_numbers import InternalAccountNumberGenerator
from application.use_cases.block_account import BlockAccount
from application.use_cases.create_account import CreateAccount
from application.use_cases.get_account import GetAccount
from application.use_cases.get_account_by_number import GetAccountByNumber
from application.use_cases.list_accounts import ListAccounts
from application.use_cases.reactivate_account import ReactivateAccount
from infrastructure.persistence.account_unit_of_work import SQLAlchemyAccountUnitOfWork
from ports.account_number_generator import AccountNumberGenerator
from ports.account_unit_of_work import AccountUnitOfWork


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


def get_account_unit_of_work(request: Request) -> AccountUnitOfWork:
    factory = cast(sessionmaker[Session] | None, request.app.state.session_factory)
    if factory is None:
        raise HTTPException(status_code=503, detail="Accounts persistence unavailable")
    return SQLAlchemyAccountUnitOfWork(factory)


AccountWorkDependency = Annotated[AccountUnitOfWork, Depends(get_account_unit_of_work)]


def get_account_number_generator() -> AccountNumberGenerator:
    return InternalAccountNumberGenerator()


def get_create_account(
    work: AccountWorkDependency,
    numbers: Annotated[AccountNumberGenerator, Depends(get_account_number_generator)],
) -> CreateAccount:
    return CreateAccount(work, numbers)


def get_get_account(work: AccountWorkDependency) -> GetAccount:
    return GetAccount(work)


def get_get_account_by_number(work: AccountWorkDependency) -> GetAccountByNumber:
    return GetAccountByNumber(work)


def get_list_accounts(work: AccountWorkDependency) -> ListAccounts:
    return ListAccounts(work)


def get_block_account(work: AccountWorkDependency) -> BlockAccount:
    return BlockAccount(work)


def get_reactivate_account(work: AccountWorkDependency) -> ReactivateAccount:
    return ReactivateAccount(work)
