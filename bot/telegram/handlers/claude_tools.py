"""Tool execution utilities for Claude handler.

This module provides safe tool execution and charging functions for the
Claude conversation handler.

NO __init__.py - use direct import:
    from telegram.handlers.claude_tools import (
        execute_single_tool_safe,
        charge_for_tool
    )
"""

from decimal import Decimal
import time
from typing import Optional

from aiogram import Bot
from aiogram import types
import config
from core.exceptions import ToolValidationError
from core.tools.cost_estimator import is_paid_tool
from core.tools.registry import execute_tool
from services.factory import ServiceFactory
from sqlalchemy.ext.asyncio import AsyncSession
from utils.metrics import record_tool_precheck_rejected
from utils.structured_logging import get_logger

logger = get_logger(__name__)


# Note: Tool execution runs WITHOUT any chat action indicator
# User requested: no status while tools are running (bot is not "typing")
# File send actions (upload_photo/document) are shown in claude_files.py
async def get_user_balance(
    user_id: int,
    session: AsyncSession,
) -> Optional[Decimal]:
    """Get user balance from cache or database.

    Tries Redis cache first, falls back to Postgres if miss.
    Used for tool cost pre-check to avoid blocking paid tools
    when balance is negative.

    Args:
        user_id: Telegram user ID.
        session: Database session for fallback query.

    Returns:
        User balance in USD, or None if user not found.
    """
    from services.balance_policy import get_balance_policy

    policy = get_balance_policy()
    balance = await policy.get_balance(user_id, session)
    return balance if balance > Decimal("0") else balance


async def charge_for_tool(
    session: AsyncSession,
    user_id: int,
    tool_name: str,
    result: dict,
    message_id: int,
) -> None:
    """Charge user for tool execution cost.

    Args:
        session: Database session.
        user_id: User to charge.
        tool_name: Name of the tool executed.
        result: Tool result containing cost_usd.
        message_id: Related message ID.
    """
    try:
        tool_cost_usd = Decimal(str(result["cost_usd"]))
        services = ServiceFactory(session)

        await services.balance.charge_user(
            user_id=user_id,
            amount=tool_cost_usd,
            description=f"Tool: {tool_name}, cost ${result['cost_usd']}",
            related_message_id=message_id,
        )
        await session.commit()

        logger.info("tools.loop.user_charged_for_tool",
                    user_id=user_id,
                    tool_name=tool_name,
                    cost_usd=float(tool_cost_usd))

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("stream.tool_charge_failed",
                     user_id=user_id,
                     tool_name=tool_name,
                     error=str(e),
                     exc_info=True)


async def execute_single_tool_safe(
    tool_name: str,
    tool_input: dict,
    bot: Bot,
    session: AsyncSession,
    thread_id: int,
    user_id: int,
    chat_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> dict:
    """Execute a single tool with error handling for parallel execution.

    This function wraps execute_tool() with try/except to allow safe use
    with asyncio.gather(). Each tool execution is independent and errors
    are captured in the result dict.

    Includes balance pre-check for paid tools (Phase 2.3):
    - If balance < 0 and tool is paid, rejects with structured error
    - Claude should inform user to top up with /pay command

    Sends appropriate chat action (typing indicator) before execution.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Tool input parameters.
        bot: Telegram Bot instance.
        session: Database session.
        thread_id: Thread ID for logging.
        user_id: User ID for balance pre-check.
        chat_id: Chat ID for typing indicator (optional).
        message_thread_id: Forum topic ID for typing indicator (optional).

    Returns:
        Dict with result or error. Always includes:
        - _tool_name: Name of the tool
        - _start_time: Execution start time
        - _duration: Execution duration in seconds
        - Either tool result keys or "error" key on failure
    """
    start_time = time.time()

    logger.info("tools.parallel.executing",
                thread_id=thread_id,
                tool_name=tool_name)

    # Phase 2.3: Balance pre-check for paid tools
    if config.TOOL_COST_PRECHECK_ENABLED and is_paid_tool(tool_name):
        balance = await get_user_balance(user_id, session)

        if balance is not None and balance < 0:
            duration = time.time() - start_time
            record_tool_precheck_rejected(tool_name)

            logger.info("tools.precheck.rejected",
                        thread_id=thread_id,
                        tool_name=tool_name,
                        user_id=user_id,
                        balance_usd=str(balance))

            return {
                "error": "insufficient_balance",
                "message":
                    (f"Cannot execute {tool_name}: your balance is negative "
                     f"(${balance:.2f}). Paid tools are blocked until balance "
                     "is topped up. Please inform the user to use /pay command."
                    ),
                "balance_usd": str(balance),
                "tool_name": tool_name,
                "_tool_name": tool_name,
                "_start_time": start_time,
                "_duration": duration,
            }

    try:
        # Execute tool WITHOUT chat action indicator
        # User requested: no status during tool execution (bot is not "typing")
        # Status will be shown when:
        # - File is being uploaded (uploading scope in claude_files.py)
        # - Bot continues writing text (generating scope in claude.py)
        result = await execute_tool(tool_name,
                                    tool_input,
                                    bot,
                                    session,
                                    thread_id=thread_id,
                                    user_id=user_id)
        duration = time.time() - start_time

        # Add metadata for post-processing
        result["_tool_name"] = tool_name
        result["_start_time"] = start_time
        result["_duration"] = duration

        logger.info("tools.parallel.success",
                    thread_id=thread_id,
                    tool_name=tool_name,
                    duration_ms=round(duration * 1000))

        return result

    except ToolValidationError as e:
        # Validation worked correctly - LLM just passed wrong params
        # Log as info since system behaved as expected
        duration = time.time() - start_time

        logger.info("tools.parallel.validation_rejected",
                    thread_id=thread_id,
                    tool_name=tool_name,
                    reason=str(e),
                    duration_ms=round(duration * 1000))

        return {
            "error": str(e),
            "_tool_name": tool_name,
            "_start_time": start_time,
            "_duration": duration,
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        # External API errors handled correctly - log as info
        duration = time.time() - start_time

        logger.info("tools.parallel.external_error",
                    thread_id=thread_id,
                    tool_name=tool_name,
                    error=str(e),
                    duration_ms=round(duration * 1000))

        return {
            "error": f"Tool execution failed: {str(e)}",
            "_tool_name": tool_name,
            "_start_time": start_time,
            "_duration": duration,
        }
