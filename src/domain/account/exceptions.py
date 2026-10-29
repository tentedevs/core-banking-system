class InvalidAccountData(ValueError):
    """Account data violates a domain invariant."""


class InvalidAccountStateTransition(ValueError):
    """The requested operation is unavailable in the account's current state."""
