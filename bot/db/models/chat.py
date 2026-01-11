"""Chat model representing Telegram chats.

This module defines the Chat model which stores information about Telegram
chats (private, groups, supergroups, channels). Uses Telegram chat_id as
primary key.

NO __init__.py - use direct import: from db.models.chat import Chat
"""

from typing import Optional

from db.models.base import Base
from db.models.base import TimestampMixin
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Chat(Base, TimestampMixin):
    """Telegram chat (private/group/supergroup/channel).

    Stores information about chats where the bot operates.
    Primary key is Telegram chat_id (globally unique, permanent).

    Chat ID ranges (from Telegram API):
    - Users: 1 to 1099511627775 (positive)
    - Groups: -1 to -999999999999 (negative)
    - Supergroups/Channels: -1997852516352 to -1000000000001

    Attributes:
        id: Telegram chat ID (globally unique across all chats).
        type: Chat type (private/group/supergroup/channel).
        title: Chat title (for groups/channels).
        username: Public username (@chatname).
        first_name: First name (private chats only).
        last_name: Last name (private chats only).
        is_forum: Whether supergroup has topics/forums enabled.
        created_at: Record creation timestamp (from TimestampMixin).
        updated_at: Record update timestamp (from TimestampMixin).
    """

    __tablename__ = "chats"

    # Primary key = Telegram chat_id (globally unique)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        doc="Telegram chat ID (-4000000000000 to 1099511627775)",
    )

    # Chat type
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Chat type: private/group/supergroup/channel",
    )

    # Chat identity (for groups/channels)
    title: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Chat title (groups/supergroups/channels)",
    )

    username: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Public username (@chatname)",
    )

    # Private chat identity
    first_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="First name (private chats only)",
    )

    last_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Last name (private chats only)",
    )

    # Forum/topics support (Bot API 9.3)
    is_forum: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Supergroup has topics/forums enabled",
    )

    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            Chat representation with ID, type, and title/username.
        """
        identifier = self.title or self.username or self.first_name or self.id
        return f"<Chat(id={self.id}, type={self.type}, name={identifier})>"
