from enum import StrEnum


class AccountProductType(StrEnum):
    SAVINGS_ACCOUNT = "SAVINGS_ACCOUNT"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"
