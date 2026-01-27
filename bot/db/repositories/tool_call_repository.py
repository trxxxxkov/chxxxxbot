"""Repository for ToolCall model.

This module provides database operations for ToolCall records,
enabling tracking of tool execution costs for accurate billing.

NO __init__.py - use direct import:
    from db.repositories.tool_call_repository import ToolCallRepository
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
from typing import Optional

from db.models.tool_call import ToolCall
from db.repositories.base import BaseRepository
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class ToolCallRepository(BaseRepository[ToolCall]):
    """Repository for managing tool call records.

    Provides methods for:
    - Recording tool executions with costs
    - Querying costs by user, tool, time period
    - Aggregated totals for billing
    """

    def __init__(self, session: AsyncSession):
        """Initialize tool call repository.

        Args:
            session: Database session.
        """
        super().__init__(session, ToolCall)

    async def create_tool_call(
        self,
        user_id: int,
        chat_id: int,
        tool_name: str,
        model_id: str,
        cost_usd: Decimal,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        thread_id: Optional[int] = None,
        message_id: Optional[int] = None,
        duration_ms: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> ToolCall:
        """Record a tool execution.

        Args:
            user_id: User who initiated the tool call.
            chat_id: Chat where tool was called.
            tool_name: Name of the tool executed.
            model_id: Model used for the tool call.
            cost_usd: Calculated cost in USD.
            input_tokens: Input tokens used.
            output_tokens: Output tokens used.
            cache_read_tokens: Cache read tokens.
            cache_creation_tokens: Cache creation tokens.
            thread_id: Thread context (optional).
            message_id: Related message ID (optional).
            duration_ms: Execution time in milliseconds (optional).
            success: Whether execution succeeded.
            error_message: Error message if failed.

        Returns:
            Created ToolCall instance.
        """
        tool_call = ToolCall(
            user_id=user_id,
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=message_id,
            tool_name=tool_name,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        )

        self.session.add(tool_call)
        await self.session.flush()

        logger.info(
            "tool_call.recorded",
            tool_name=tool_name,
            user_id=user_id,
            model_id=model_id,
            cost_usd=float(cost_usd),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return tool_call

    async def get_user_tool_costs(
        self,
        user_id: int,
        period: str = "all",
    ) -> Decimal:
        """Get total tool costs for a user.

        Args:
            user_id: Telegram user ID.
            period: Time period - "today", "week", "month", or "all".

        Returns:
            Total USD cost of tool calls.
        """
        stmt = select(func.sum(ToolCall.cost_usd)).where(
            ToolCall.user_id == user_id,
            ToolCall.success.is_(True),
        )

        # Add time filter
        if period != "all":
            now = datetime.now(timezone.utc)
            if period == "today":
                start_time = now.replace(hour=0,
                                         minute=0,
                                         second=0,
                                         microsecond=0)
            elif period == "week":
                start_time = now - timedelta(days=7)
            elif period == "month":
                start_time = now - timedelta(days=30)
            else:
                start_time = datetime.min.replace(tzinfo=timezone.utc)

            stmt = stmt.where(ToolCall.created_at >= start_time)

        result = await self.session.execute(stmt)
        total = result.scalar() or Decimal("0.000000")

        logger.debug(
            "tool_call.user_costs",
            user_id=user_id,
            period=period,
            total=float(total),
        )

        return total

    async def get_costs_by_tool(
        self,
        period: str = "all",
    ) -> dict[str, Decimal]:
        """Get costs aggregated by tool name.

        Args:
            period: Time period - "today", "week", "month", or "all".

        Returns:
            Dict mapping tool_name to total cost.
        """
        stmt = select(
            ToolCall.tool_name,
            func.sum(ToolCall.cost_usd).label("total_cost"),
        ).where(ToolCall.success.is_(True)).group_by(ToolCall.tool_name)

        # Add time filter
        if period != "all":
            now = datetime.now(timezone.utc)
            if period == "today":
                start_time = now.replace(hour=0,
                                         minute=0,
                                         second=0,
                                         microsecond=0)
            elif period == "week":
                start_time = now - timedelta(days=7)
            elif period == "month":
                start_time = now - timedelta(days=30)
            else:
                start_time = datetime.min.replace(tzinfo=timezone.utc)

            stmt = stmt.where(ToolCall.created_at >= start_time)

        result = await self.session.execute(stmt)
        rows = result.all()

        costs = {row.tool_name: row.total_cost or Decimal("0") for row in rows}

        logger.debug(
            "tool_call.costs_by_tool",
            period=period,
            tool_count=len(costs),
            total=float(sum(costs.values())),
        )

        return costs

    async def get_total_cost(self, period: str = "all") -> Decimal:
        """Get total tool costs for all users.

        Args:
            period: Time period - "today", "week", "month", or "all".

        Returns:
            Total USD cost.
        """
        stmt = select(func.sum(ToolCall.cost_usd)).where(
            ToolCall.success.is_(True))

        # Add time filter
        if period != "all":
            now = datetime.now(timezone.utc)
            if period == "today":
                start_time = now.replace(hour=0,
                                         minute=0,
                                         second=0,
                                         microsecond=0)
            elif period == "week":
                start_time = now - timedelta(days=7)
            elif period == "month":
                start_time = now - timedelta(days=30)
            else:
                start_time = datetime.min.replace(tzinfo=timezone.utc)

            stmt = stmt.where(ToolCall.created_at >= start_time)

        result = await self.session.execute(stmt)
        total = result.scalar() or Decimal("0.000000")

        return total
