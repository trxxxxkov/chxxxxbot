"""User model representing Telegram users.

This module defines the User model which stores information about Telegram
users interacting with the bot. Uses Telegram user_id as primary key.

NO __init__.py - use direct import: from db.models.user import User
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from db.models.base import Base
from db.models.base import TimestampMixin
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

if TYPE_CHECKING:
    from db.models.balance_operation import BalanceOperation
    from db.models.payment import Payment


class User(Base, TimestampMixin):
    """Telegram user with bot preferences and balance.

    Stores Telegram user information, bot-specific settings, and payment balance.
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
        custom_prompt: Personal instructions (personality, tone, style).
        balance: User balance in USD (default $0.10 starter balance).
        message_count: Total messages sent by user.
        total_tokens_used: Total tokens consumed (input + output).
        first_seen_at: When user first interacted with bot.
        last_seen_at: Last activity timestamp.
        created_at: Record creation timestamp (from TimestampMixin).
        updated_at: Record update timestamp (from TimestampMixin).
        payments: Related payment transactions.
        balance_operations: Related balance change operations.
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

    allows_users_to_create_topics: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="Whether bot allows users to create topics in private chat "
        "(Bot API 9.4)",
    )

    # Bot-specific settings (per user, not per thread!)
    model_id: Mapped[str] = mapped_column(
        String(100),  # Fits "provider:alias" format (e.g., "claude:sonnet")
        nullable=False,
        default="claude:sonnet",  # Default: Claude Sonnet 4.6
        doc="Model identifier in format 'provider:alias' "
        "(e.g., 'claude:sonnet', 'openai:gpt4')",
    )

    # Phase 1.4.2: 3-level system prompt architecture
    custom_prompt: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="User's personal instructions (personality, tone, style). "
        "Added to GLOBAL_SYSTEM_PROMPT. Can be cached.",
    )

    # Phase 2.1: Payment system
    balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        default=Decimal("0.1000"),
        server_default="0.1000",
        doc="User balance in USD. Default: $0.10 starter balance. "
        "Allows requests while balance > 0 (can go negative after one request).",
    )

    # Activity tracking & statistics
    message_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        doc="Total messages sent by user (for activity tracking)",
    )

    total_tokens_used: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        doc="Total tokens consumed (input + output) for cost analysis",
    )

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

    # Relationships (Phase 2.1: Payment system)
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's payment transactions (top-ups via Telegram Stars)",
    )

    balance_operations: Mapped[list["BalanceOperation"]] = relationship(
        "BalanceOperation",
        foreign_keys="[BalanceOperation.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="Complete audit trail of all balance changes",
    )

    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            User representation with ID and username.
        """
        return f"<User(id={self.id}, username={self.username})>"
