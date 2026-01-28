"""Thread model for conversation threads.

This module defines the Thread model which stores conversation threads
based on Telegram thread_id (forum topics). Each user has separate threads
per topic for personalized LLM context.

NO __init__.py - use direct import: from db.models.thread import Thread
"""

from typing import Optional

from db.models.base import Base
from db.models.base import TimestampMixin
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Thread(Base, TimestampMixin):
    """Conversation thread (forum topic or private chat thread).

    Stores conversation threads for LLM context management.
    Each user has separate threads per topic (identified by thread_id
    from Telegram Bot API 9.3).

    Thread Logic:
    - thread_id = NULL → main chat (no forum topic)
    - thread_id = 123 → Telegram forum topic with ID 123
    - Each user has separate threads per topic for personalized context
    - LLM context = all messages in this thread
    - Model selection is per user (User.model_id), not per thread

    Phase 1.4.2 system prompt architecture (3-level):
    - GLOBAL_SYSTEM_PROMPT (config.py) - cached, same for all
    - User.custom_prompt (per user) - cached, personal instructions
    - Thread.files_context (per thread) - NOT cached, auto-generated file list

    Attributes:
        id: Internal thread ID (auto-increment).
        chat_id: Which chat this thread belongs to.
        user_id: Which user this thread belongs to.
        thread_id: Telegram thread/topic ID (NULL for main chat).
        title: Thread title (manual or LLM-generated).
        files_context: List of files available in this thread.
        needs_topic_naming: Whether topic needs LLM-generated name.
        created_at: When thread started (from TimestampMixin).
        updated_at: Last message timestamp (from TimestampMixin).
    """

    __tablename__ = "threads"

    # Internal ID for foreign keys
    # Note: Integer for SQLite autoincrement, BigInteger for PostgreSQL
    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger, "postgresql"),
        primary_key=True,
        autoincrement=True,
        doc="Internal thread ID",
    )

    # Foreign keys
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        doc="Chat where thread exists",
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who owns this thread",
    )

    # Telegram thread ID (from Bot API 9.3)
    thread_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Telegram thread/topic ID (NULL = main chat)",
    )

    # Thread metadata
    title: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Thread title",
    )

    # Phase 1.4.2: 3-level system prompt architecture
    files_context: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Auto-generated list of files available in this thread. "
        "Added to system prompt. NOT cached (changes frequently).",
    )

    # Bot API 9.3: Topic naming for private chats with topics
    needs_topic_naming: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="Whether this topic needs LLM-generated name. "
        "Set True on creation, False after naming.",
    )

    # Topic clearing: marks thread as belonging to deleted topic
    is_cleared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="Whether the Telegram topic for this thread has been deleted. "
        "Cleared threads are excluded from topic counts.",
    )

    # Indexes and constraints
    __table_args__ = (
        # Unique constraint: one thread per user per topic
        # Note: This allows multiple NULL thread_id values (main chat threads)
        # PostgreSQL partial unique index created via Alembic migration
        UniqueConstraint(
            "chat_id",
            "user_id",
            "thread_id",
            name="uq_threads_chat_user_thread",
        ),
        # Index for finding threads by chat and user
        Index("idx_threads_chat_user", "chat_id", "user_id"),
        # Index for finding threads by thread_id
        Index("idx_threads_thread_id", "thread_id"),
    )

    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            Thread representation with ID, chat, user, and thread_id.
        """
        return (f"<Thread(id={self.id}, chat_id={self.chat_id}, "
                f"user_id={self.user_id}, thread_id={self.thread_id})>")
