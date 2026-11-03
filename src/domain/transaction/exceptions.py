class InvalidTransactionData(ValueError):
    """A banking transaction violates a domain data invariant."""


class InvalidAccountMovementData(ValueError):
    """An account movement violates a domain data invariant."""
