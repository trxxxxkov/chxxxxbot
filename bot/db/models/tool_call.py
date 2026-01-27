"""Tool call model for tracking tool execution costs.

This module defines the ToolCall model which stores all tool executions
with their associated costs for accurate billing tracking.

NO __init__.py - use direct import:
    from db.models.tool_call import ToolCall
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from db.models.base import Base
from sqlalchemy import BigInteger
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import func
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class ToolCall(Base):
    """Tool execution record with cost tracking.

    Stores all tool executions (analyze_image, analyze_pdf, etc.)
    with their token usage and costs for accurate billing.

    Attributes:
        id: Auto-incrementing primary key.
        user_id: User who initiated the tool call.
        chat_id: Chat where tool was called.
        thread_id: Thread context.
        message_id: Related message ID (if any).
        tool_name: Name of the tool executed.
        model_id: Model used for the tool call (e.g., claude-opus-4-5).
        input_tokens: Input tokens used.
        output_tokens: Output tokens used.
        cache_read_tokens: Cache read tokens (if applicable).
        cache_creation_tokens: Cache creation tokens (if applicable).
        cost_usd: Calculated cost in USD.
        duration_ms: Execution time in milliseconds.
        success: Whether execution succeeded.
        error_message: Error message if failed.
        created_at: When the tool was called.
    """

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        doc="Auto-incrementing primary key",
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who initiated the tool call",
    )

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        doc="Chat where tool was called",
    )

    thread_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("threads.id", ondelete="SET NULL"),
        nullable=True,
        doc="Thread context",
    )

    message_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Related Telegram message ID",
    )

    tool_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Name of the tool executed",
    )

    model_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Model used for the tool call",
    )

    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Input tokens used",
    )

    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Output tokens used",
    )

    cache_read_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Cache read tokens",
    )

    cache_creation_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Cache creation tokens",
    )

    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=6),
        nullable=False,
        doc="Calculated cost in USD",
    )

    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Execution time in milliseconds",
    )

    success: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        doc="Whether execution succeeded",
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if failed",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When the tool was called",
    )

    __table_args__ = (
        Index("idx_tool_calls_user", "user_id"),
        Index("idx_tool_calls_chat", "chat_id"),
        Index("idx_tool_calls_created", "created_at"),
        Index("idx_tool_calls_tool_name", "tool_name"),
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"<ToolCall(id={self.id}, tool={self.tool_name}, "
                f"cost=${self.cost_usd})>")
