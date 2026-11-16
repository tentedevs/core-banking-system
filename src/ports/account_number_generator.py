from typing import Protocol


class AccountNumberGenerator(Protocol):
    def generate(self) -> str:
        """Return a candidate internal identifier; the database enforces uniqueness."""
        ...
