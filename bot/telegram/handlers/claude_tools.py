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
from cache.user_cache import get_balance_from_cached
from cache.user_cache import get_cached_user
import config
from core.exceptions import ToolValidationError
from core.tools.cost_estimator import is_paid_tool
from core.tools.registry import execute_tool
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
from services.balance_service import BalanceService
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.chat_action import ChatAction
from telegram.chat_action import send_action
from utils.metrics import record_tool_precheck_rejected
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Map tool names to appropriate chat actions
TOOL_CHAT_ACTIONS: dict[str, ChatAction] = {
    # Image/media tools
    "generate_image": "upload_photo",
    "analyze_image": "upload_photo",
    "analyze_pdf": "upload_document",
    "render_latex": "upload_photo",
    # Audio tools
    "transcribe_audio": "record_voice",
    # File tools
    "execute_python": "typing",
    "deliver_file": "upload_document",
    "preview_file": "upload_photo",
    # Default for others
    "web_search": "typing",
    "web_fetch": "typing",
}


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
    # Try cache first
    cached = await get_cached_user(user_id)
    if cached:
        return get_balance_from_cached(cached)

    # Fallback to database
    user_repo = UserRepository(session)
    user = await user_repo.get(user_id)
    if user:
        return user.balance

    return None


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
        user_repo = UserRepository(session)
        balance_op_repo = BalanceOperationRepository(session)
        balance_service = BalanceService(session, user_repo, balance_op_repo)

        await balance_service.charge_user(
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

    # Send appropriate chat action for this tool
    if chat_id:
        action = TOOL_CHAT_ACTIONS.get(tool_name, "typing")
        await send_action(bot, chat_id, action, message_thread_id)

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
        result = await execute_tool(tool_name,
                                    tool_input,
                                    bot,
                                    session,
                                    thread_id=thread_id)
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
