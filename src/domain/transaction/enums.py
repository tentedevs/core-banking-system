from enum import StrEnum


class TransactionType(StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class MovementDirection(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
