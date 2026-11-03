class InvalidAccountBalanceData(ValueError):
    """Balance data violates a projection invariant."""


class InsufficientFunds(ValueError):
    """An ordinary debit exceeds available funds."""
