"""Tool execution for streaming responses.

Handles parallel tool execution with proper charging, metrics, and cleanup.
Extracted from claude.py for better separation of concerns.

NO __init__.py - use direct import:
    from telegram.streaming.tool_executor import ToolExecutor
"""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal
from typing import Awaitable, Callable, TYPE_CHECKING

from cache.write_behind import queue_write
from cache.write_behind import WriteType
from telegram.handlers.claude_tools import charge_for_tool
from telegram.handlers.claude_tools import execute_single_tool_safe
from telegram.streaming.types import ToolCall
from utils.metrics import record_cost
from utils.metrics import record_error
from utils.metrics import record_tool_call
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from asyncio import Event

    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass
class ToolExecutionResult:
    """Result of a single tool execution.

    Attributes:
        tool: The tool call that was executed.
        result: Cleaned result dict (without _ prefixed keys).
        raw_result: Original result with metadata.
        is_error: True if tool execution failed.
        duration: Execution duration in seconds.
        cost_usd: Cost in USD (if applicable).
        force_turn_break: True if tool requested turn break.
    """

    tool: ToolCall
    result: dict
    raw_result: dict
    is_error: bool = False
    duration: float = 0.0
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    force_turn_break: bool = False


@dataclass
class BatchExecutionResult:
    """Result of parallel tool batch execution.

    Attributes:
        results: List of ToolExecutionResult in original order.
        force_turn_break: True if any tool requested turn break.
        turn_break_tool: Name of tool that triggered turn break.
        first_file_committed: True if files were committed during execution.
    """

    results: list[ToolExecutionResult]
    force_turn_break: bool = False
    turn_break_tool: str | None = None
    first_file_committed: bool = False


class ToolExecutor:
    """Executes tools in parallel with proper handling.

    Manages:
    - Parallel execution via asyncio.as_completed
    - Cost charging
    - Metrics recording
    - Database queuing for tool calls
    """

    def __init__(
        self,
        bot: "Bot",
        session: "AsyncSession",
        thread_id: int,
        user_id: int,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None = None,
    ):
        """Initialize ToolExecutor.

        Args:
            bot: Telegram Bot instance.
            session: Database session.
            thread_id: Thread ID for logging.
            user_id: User ID for charging.
            chat_id: Chat ID for typing indicator.
            message_id: Message ID for charge records.
            message_thread_id: Forum topic ID.
        """
        self._bot = bot
        self._session = session
        self._thread_id = thread_id
        self._user_id = user_id
        self._chat_id = chat_id
        self._message_id = message_id
        self._message_thread_id = message_thread_id

    async def execute_batch(
        self,
        tools: list[ToolCall],
        cancel_event: "Event | None" = None,
        on_file_ready: "Callable | None" = None,
        on_subagent_tool: "Callable[[str, str], Awaitable[None]] | None" = None,
        on_thinking_chunk: "Callable[[str], Awaitable[None]] | None" = None,
        model_id: str | None = None,
    ) -> BatchExecutionResult:
        """Execute tools in parallel, process results as completed.

        Args:
            tools: List of ToolCall to execute.
            cancel_event: Optional event to check for cancellation.
            on_file_ready: Callback for file processing (called for each file).
            on_subagent_tool: Callback (parent_tool, sub_tool) for subagent progress.
            on_thinking_chunk: Callback for extended_think thinking chunks.
            model_id: User's current model ID (for extended_think).

        Returns:
            BatchExecutionResult with all results in original order.
        """
        if not tools:
            return BatchExecutionResult(results=[])

        tool_names = [t.name for t in tools]
        logger.info(
            "tool_executor.batch_start",
            thread_id=self._thread_id,
            tool_count=len(tools),
            tool_names=tool_names,
        )

        # Create indexed tasks for as_completed processing
        async def _indexed_task(idx: int, tool: ToolCall) -> tuple:
            # Create callback for self_critique subagent tool progress
            tool_callback = None
            if tool.name == "self_critique" and on_subagent_tool:

                async def _subagent_callback(sub_tool: str) -> None:
                    await on_subagent_tool(tool.name, sub_tool)

                tool_callback = _subagent_callback

            # Create callback for extended_think thinking chunks
            thinking_callback = None
            if tool.name == "extended_think" and on_thinking_chunk:
                thinking_callback = on_thinking_chunk

            # Add model_id for extended_think
            extra_kwargs = {}
            if tool.name == "extended_think" and model_id:
                extra_kwargs["model_id"] = model_id

            result = await execute_single_tool_safe(
                tool_name=tool.name,
                tool_input=tool.input,
                bot=self._bot,
                session=self._session,
                thread_id=self._thread_id,
                user_id=self._user_id,
                chat_id=self._chat_id,
                message_thread_id=self._message_thread_id,
                on_subagent_tool=tool_callback,
                on_thinking_chunk=thinking_callback,
                cancel_event=cancel_event,
                **extra_kwargs,
            )
            return (idx, result)

        tasks = [_indexed_task(idx, tool) for idx, tool in enumerate(tools)]

        # Process results as they complete
        results: list[ToolExecutionResult | None] = [None] * len(tools)
        first_file_committed = False
        force_turn_break = False
        turn_break_tool = None

        for coro in asyncio.as_completed(tasks):
            idx, raw_result = await coro
            tool = tools[idx]
            duration = raw_result.get("_duration", 0)
            is_error = bool(raw_result.get("error"))

            # Clean result (remove _ prefixed keys)
            clean_result = {
                k: v for k, v in raw_result.items() if not k.startswith("_")
            }
            if is_error:
                clean_result["error"] = raw_result["error"]

            # Process successful tool
            cost_usd = Decimal("0")
            if not is_error:
                # Handle file delivery
                if raw_result.get("_file_contents"):
                    is_cancelled = cancel_event and cancel_event.is_set()
                    if not is_cancelled and on_file_ready:
                        if not first_file_committed:
                            first_file_committed = True
                        await on_file_ready(raw_result, tool)
                    elif is_cancelled:
                        logger.info(
                            "tool_executor.file_skipped_cancelled",
                            thread_id=self._thread_id,
                            tool_name=tool.name,
                        )

                # Check for turn break
                if raw_result.get("_force_turn_break"):
                    force_turn_break = True
                    turn_break_tool = tool.name
                    logger.info(
                        "tool_executor.turn_break_requested",
                        thread_id=self._thread_id,
                        tool_name=tool.name,
                    )

                # Charge user for tool cost
                # Skip if tool already charged internally (e.g., self_critique)
                if "cost_usd" in clean_result and not clean_result.get(
                        "_already_charged"):
                    cost_usd = Decimal(str(clean_result["cost_usd"]))
                    await charge_for_tool(
                        self._session,
                        self._user_id,
                        tool.name,
                        clean_result,
                        self._message_id,
                    )

                # Record metrics
                record_tool_call(tool_name=tool.name,
                                 success=True,
                                 duration=duration)
                if "cost_usd" in clean_result:
                    record_cost(
                        service=tool.name,
                        amount_usd=float(clean_result["cost_usd"]),
                    )

                # Queue tool call to database
                if "_model_id" in raw_result:
                    tool_call_data = {
                        "user_id":
                            self._user_id,
                        "chat_id":
                            self._chat_id,
                        "thread_id":
                            self._thread_id,
                        "message_id":
                            self._message_id,
                        "tool_name":
                            tool.name,
                        "model_id":
                            raw_result["_model_id"],
                        "input_tokens":
                            raw_result.get("_input_tokens", 0),
                        "output_tokens":
                            raw_result.get("_output_tokens", 0),
                        "cache_read_tokens":
                            raw_result.get("_cache_read_tokens", 0),
                        "cache_creation_tokens":
                            raw_result.get("_cache_creation_tokens", 0),
                        "cost_usd":
                            float(clean_result["cost_usd"]),
                        "duration_ms":
                            int(duration * 1000) if duration else None,
                        "success":
                            True,
                    }
                    await queue_write(WriteType.TOOL_CALL, tool_call_data)
            else:
                # Record error metrics
                record_tool_call(tool_name=tool.name,
                                 success=False,
                                 duration=duration)
                record_error(error_type="tool_execution", handler=tool.name)

            results[idx] = ToolExecutionResult(
                tool=tool,
                result=clean_result,
                raw_result=raw_result,
                is_error=is_error,
                duration=duration,
                cost_usd=cost_usd,
                force_turn_break=raw_result.get("_force_turn_break", False),
            )

        logger.info(
            "tool_executor.batch_complete",
            thread_id=self._thread_id,
            tool_count=len(tools),
            errors=sum(1 for r in results if r and r.is_error),
            force_turn_break=force_turn_break,
        )

        return BatchExecutionResult(
            results=[r for r in results if r is not None],
            force_turn_break=force_turn_break,
            turn_break_tool=turn_break_tool,
            first_file_committed=first_file_committed,
        )
