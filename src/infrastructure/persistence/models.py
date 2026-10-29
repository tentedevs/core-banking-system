"""Shared SQLAlchemy metadata; business models are added separately."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
