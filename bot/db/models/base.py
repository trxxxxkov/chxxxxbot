"""Base model with common fields for all tables.

This module provides the declarative base class and mixins for all
database models. NO __init__.py files - use direct imports.
"""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Base(DeclarativeBase):
    """Base class for all database models.

    All models inherit from this class to be registered with SQLAlchemy.
    Provides common configuration for all tables.
    """


class TimestampMixin:
    """Mixin adding created_at and updated_at timestamps.

    Automatically tracks when records are created and updated.
    Uses server-side NOW() for consistency across database operations.

    Attributes:
        created_at: Timestamp when record was created (auto-set on insert).
        updated_at: Timestamp when record was last updated (auto-updated).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When record was created",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="When record was last updated",
    )
