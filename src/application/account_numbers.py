from uuid import uuid4


class InternalAccountNumberGenerator:
    """33-character internal reference: C + UUID4 hex. This is not an IBAN."""

    def generate(self) -> str:
        return f"C{uuid4().hex}"
