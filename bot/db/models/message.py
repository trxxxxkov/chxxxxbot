"""Message model for storing Telegram messages.

This module defines the Message model which stores all Telegram messages
for conversation history. Uses composite primary key (chat_id, message_id)
matching Telegram's identification scheme.

NO __init__.py - use direct import:
    from db.models.message import Message, MessageRole
"""

import enum
from typing import Optional

from db.models.base import Base
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class MessageRole(str, enum.Enum):
    """Message role in LLM conversation.

    Attributes:
        USER: Message from user.
        ASSISTANT: Response from LLM.
        SYSTEM: System prompt.
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(Base):
    """Telegram message with conversation history.

    Stores all Telegram messages for LLM context. Uses composite primary
    key (chat_id, message_id) matching Telegram's identification.

    JSONB attachments stores full attachment metadata with denormalized
    boolean flags (has_photos, etc.) for fast filtering.

    Attributes:
        chat_id: Chat where message was sent (part of composite PK).
        message_id: Telegram message ID (part of composite PK).
        thread_id: Which thread this message belongs to.
        from_user_id: Message sender (NULL for channels).
        date: Unix timestamp when sent.
        edit_date: Unix timestamp of last edit.
        role: Message role for LLM API (user/assistant/system).
        text_content: Text content.
        caption: Media caption.
        reply_to_message_id: Replied message ID.
        media_group_id: Groups related media messages.
        has_photos: Denormalized flag for photo attachments.
        has_documents: Denormalized flag for document attachments.
        has_voice: Denormalized flag for voice messages.
        has_video: Denormalized flag for video attachments.
        attachment_count: Total number of attachments.
        attachments: JSONB with full attachment metadata.
        input_tokens: LLM input tokens (for billing).
        output_tokens: LLM output tokens (for billing).
        created_at: Record creation timestamp.
    """

    __tablename__ = "messages"

    # Composite primary key (chat_id, message_id)
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chats.id", ondelete="CASCADE"),
        primary_key=True,
        doc="Chat where message was sent",
    )

    message_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        doc="Telegram message ID (unique within chat)",
    )

    # Foreign keys
    thread_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("threads.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which thread this belongs to",
    )

    from_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Message sender (NULL for channels)",
    )

    # Telegram message metadata
    date: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Unix timestamp when sent",
    )

    edit_date: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Unix timestamp of last edit",
    )

    # LLM context
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole),
        nullable=False,
        doc="Message role for LLM API",
    )

    # Message content
    text_content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Text content",
    )

    caption: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Media caption",
    )

    # Reply information
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Replied message ID (within same chat)",
    )

    media_group_id: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Groups related media messages",
    )

    # Denormalized attachment flags (for fast filtering with B-tree)
    has_photos: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Has photo attachments",
    )

    has_documents: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Has document attachments",
    )

    has_voice: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Has voice messages",
    )

    has_video: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Has video attachments",
    )

    attachment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of attachments",
    )

    # JSONB for full attachment metadata (JSON for SQLite compatibility)
    attachments: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default=text("'[]'"),
        doc=
        "Full attachment metadata (JSONB array for PostgreSQL, JSON for SQLite)",
    )

    # LLM token tracking
    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="LLM input tokens (for billing)",
    )

    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="LLM output tokens (for billing)",
    )

    # Phase 1.4.2: Prompt Caching token tracking
    cache_creation_input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Cache creation tokens (5m: 1.25x, 1h: 1.05x)",
    )

    cache_read_input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Cache read tokens (0.1x for reads)",
    )

    # Phase 1.5: Extended Thinking support
    thinking_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Extended thinking tokens (for billing)",
    )

    thinking_blocks: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Extended thinking content (can be large, full reasoning)",
    )

    # Timestamp (no TimestampMixin - we have date from Telegram)
    # But add created_at for record creation tracking
    # Note: No server_default for cross-database compatibility
    # Set in application code or use date field from Telegram
    created_at: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Record creation timestamp (Unix)",
    )

    # Indexes and constraints
    __table_args__ = (
        # Index for finding messages by thread
        Index(
            "idx_messages_thread",
            "thread_id",
            postgresql_where=(thread_id.isnot(None)),
        ),
        # Index for finding messages by sender
        Index(
            "idx_messages_from_user",
            "from_user_id",
            postgresql_where=(from_user_id.isnot(None)),
        ),
        # Index for sorting by date
        Index("idx_messages_date", "date"),
        # Index for filtering by role
        Index("idx_messages_role", "role"),
        # Index for media groups
        Index(
            "idx_messages_media_group",
            "media_group_id",
            postgresql_where=(media_group_id.isnot(None)),
        ),
        # Denormalized attachment flags (B-tree for fast simple queries)
        Index(
            "idx_messages_has_photos",
            "has_photos",
            postgresql_where=(has_photos.is_(True)),
        ),
        Index(
            "idx_messages_has_documents",
            "has_documents",
            postgresql_where=(has_documents.is_(True)),
        ),
        Index(
            "idx_messages_has_voice",
            "has_voice",
            postgresql_where=(has_voice.is_(True)),
        ),
        # GIN index on JSONB for complex attachment queries
        Index(
            "idx_messages_attachments_gin",
            "attachments",
            postgresql_using="gin",
            postgresql_ops={"attachments": "jsonb_path_ops"},
        ),
        # Foreign key constraint for reply messages
        # (ForeignKeyConstraint not needed - using application-level logic)
    )

    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            Message representation with chat, message_id, and role.
        """
        return (
            f"<Message(chat_id={self.chat_id}, message_id={self.message_id}, "
            f"role={self.role.value})>")
