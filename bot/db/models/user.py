"""User model representing Telegram users.

This module defines the User model which stores information about Telegram
users interacting with the bot. Uses Telegram user_id as primary key.

NO __init__.py - use direct import: from db.models.user import User
"""

from datetime import datetime
from typing import Optional

from db.models.base import Base
from db.models.base import TimestampMixin
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class User(Base, TimestampMixin):
    """Telegram user with bot preferences.

    Stores Telegram user information and bot-specific settings.
    Primary key is Telegram user_id (globally unique, permanent).

    Attributes:
        id: Telegram user ID (globally unique across all peers).
        is_bot: Whether this is a bot account.
        first_name: User's first name (required by Telegram).
        last_name: User's last name (optional).
        username: Telegram username for mentions (@username).
        language_code: IETF language tag (e.g., "en", "ru-RU").
        is_premium: Whether user has Telegram Premium subscription.
        added_to_attachment_menu: Whether bot added to attachment menu.
        model_id: Selected LLM model (e.g., "claude:sonnet", "openai:gpt4").
        first_seen_at: When user first interacted with bot.
        last_seen_at: Last activity timestamp.
        created_at: Record creation timestamp (from TimestampMixin).
        updated_at: Record update timestamp (from TimestampMixin).
    """

    __tablename__ = "users"

    # Primary key = Telegram user_id (globally unique)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        doc="Telegram user ID (1 to 1099511627775)",
    )

    # Telegram profile data (from User object)
    is_bot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether this is a bot account",
    )

    first_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="User's first name (required by Telegram)",
    )

    last_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="User's last name",
    )

    username: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        unique=True,
        doc="Telegram username (@username)",
    )

    language_code: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        doc="IETF language tag (e.g., en, ru-RU)",
    )

    # Telegram Premium features
    is_premium: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Telegram Premium subscription status",
    )

    added_to_attachment_menu: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Bot added to attachment menu",
    )

    # Bot-specific settings (per user, not per thread!)
    model_id: Mapped[str] = mapped_column(
        String(100),  # Fits "provider:alias" format (e.g., "claude:sonnet")
        nullable=False,
        default="claude:sonnet",  # Default: Claude Sonnet 4.5
        doc="Model identifier in format 'provider:alias' "
        "(e.g., 'claude:sonnet', 'openai:gpt4')",
    )

    # Activity tracking
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="When user first used bot",
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Last activity timestamp",
    )

    # Relationships
    # threads: Mapped[list["Thread"]] = relationship(
    #     "Thread",
    #     back_populates="user",
    #     cascade="all, delete-orphan",
    # )

    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            User representation with ID and username.
        """
        return f"<User(id={self.id}, username={self.username})>"
