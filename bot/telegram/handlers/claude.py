"""Claude conversation processing.

This module provides the core Claude API integration:
- ClaudeProvider initialization
- Message batch processing (_process_message_batch)
- Streaming with tool execution (_stream_with_unified_events)
- File handling for generated content

The message handling entry point is in telegram.pipeline.handler (unified pipeline).

# pylint: disable=too-many-lines

NO __init__.py - use direct import:
    from telegram.handlers.claude import init_claude_provider
    from telegram.handlers.claude import _process_message_batch
"""

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
import html as html_lib
import re
import time
from typing import Optional, TYPE_CHECKING

from aiogram import types
from aiogram.exceptions import TelegramRetryAfter

if TYPE_CHECKING:
    from telegram.pipeline.models import ProcessedMessage

from cache.exec_cache import get_pending_files_for_thread
from cache.thread_cache import invalidate_messages
from cache.thread_cache import update_cached_messages
from cache.write_behind import queue_write
from cache.write_behind import WriteType
import config
from config import CLAUDE_TOKEN_BUFFER_PERCENT
from config import DRAFT_KEEPALIVE_INTERVAL
from config import FILES_API_TTL_HOURS
from config import get_model
from config import GLOBAL_SYSTEM_PROMPT
from config import TOOL_LOOP_MAX_ITERATIONS
from core.claude.client import ClaudeProvider
from core.claude.context import ContextManager
from core.claude.files_api import upload_to_files_api
from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import ContextWindowExceededError
from core.exceptions import LLMError
from core.exceptions import RateLimitError
from core.exceptions import ToolValidationError
from core.models import LLMRequest
from core.models import Message
from core.tools.helpers import extract_tool_uses
from core.tools.helpers import format_tool_results
from core.tools.helpers import format_unified_files_section
from core.tools.helpers import get_available_files
from core.tools.registry import execute_tool
from core.tools.registry import get_tool_definitions
from core.tools.registry import get_tool_system_message
from db.engine import get_session
from db.models.message import MessageRole
from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_file_repository import UserFileRepository
from db.repositories.user_repository import UserRepository
from services.balance_service import BalanceService
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.context.extractors import extract_message_context
from telegram.context.formatter import ContextFormatter
from telegram.draft_streaming import DraftManager
from telegram.generation_tracker import generation_context
from telegram.handlers.claude_files import process_generated_files
from telegram.handlers.claude_helpers import compose_system_prompt_blocks
from telegram.handlers.claude_helpers import split_text_smart
from telegram.handlers.claude_tools import charge_for_tool
from telegram.handlers.claude_tools import execute_single_tool_safe
from telegram.streaming import escape_html
from telegram.streaming import StreamingSession
from telegram.streaming import strip_tool_markers as _strip_tool_markers
from telegram.streaming import ToolCall
from utils.metrics import record_cache_hit
from utils.metrics import record_cache_miss
from utils.metrics import record_claude_request
from utils.metrics import record_claude_response_time
from utils.metrics import record_claude_tokens
from utils.metrics import record_cost
from utils.metrics import record_error
from utils.metrics import record_message_sent
from utils.metrics import record_messages_batched
from utils.metrics import record_tool_call
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Global Claude provider instance (initialized in main.py)
claude_provider: ClaudeProvider = None


def init_claude_provider(api_key: str) -> None:
    """Initialize global Claude provider.

    Must be called once during application startup.

    Args:
        api_key: Claude API key from secrets.
    """
    global claude_provider  # pylint: disable=global-statement
    claude_provider = ClaudeProvider(api_key=api_key)
    logger.info("claude_handler.provider_initialized")


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# pylint: disable=too-many-nested-blocks,too-many-return-statements
async def _stream_with_unified_events(
    request: LLMRequest,
    first_message: types.Message,
    thread_id: int,
    session: AsyncSession,
    user_file_repo: UserFileRepository,
    chat_id: int,
    user_id: int,
    telegram_thread_id: int | None,
    continuation_conversation: list | None = None,
) -> tuple[str, types.Message | None, bool, list | None, bool, int, int]:
    """Stream response with unified thinking/text/tool handling.

    Uses sendMessageDraft (Bot API 9.3) for streaming without flood control.

    Unified streaming approach:
    1. Stream thinking and text together via draft updates (animated)
    2. On tool_use: append [emoji tool_name], execute, continue
    3. Finalize draft to permanent message at the end
    4. Return final answer text and final message

    Phase 3.4: Sequential delivery support
    - If tool returns _force_turn_break, stops iteration early
    - Returns needs_continuation=True so caller can continue in new call
    - Conversation state is returned for continuation

    Args:
        request: LLMRequest with tools configured.
        first_message: First Telegram message (for replies).
        thread_id: Thread ID for logging.
        session: Database session.
        user_file_repo: UserFileRepository for file handling.
        chat_id: Telegram chat ID.
        user_id: User ID.
        telegram_thread_id: Telegram thread/topic ID.
        continuation_conversation: If continuing from previous call,
            the conversation state to resume from.

    Returns:
        Tuple of (final_answer_text, final_message, needs_continuation,
                  conversation_state, was_cancelled, thinking_chars, output_chars).
        - needs_continuation: True if _force_turn_break was triggered
        - conversation_state: Updated conversation for continuation
        - was_cancelled: True if user cancelled via /stop or new message
        - thinking_chars: Character count of thinking (for partial cost estimate)
        - output_chars: Character count of output text (for partial cost estimate)
    """
    max_iterations = TOOL_LOOP_MAX_ITERATIONS

    # Build conversation for tool loop
    # Use continuation_conversation if resuming, otherwise build from request
    if continuation_conversation is not None:
        conversation = continuation_conversation
        logger.info("stream.unified.continuation",
                    thread_id=thread_id,
                    conversation_length=len(conversation))
    else:
        conversation = [{
            "role": msg.role,
            "content": msg.content
        } for msg in request.messages]

    logger.info("stream.unified.start",
                thread_id=thread_id,
                max_iterations=max_iterations,
                streaming_method="sendMessageDraft")

    # Phase 2.5: Generation tracking for /stop command
    # Combined async with to avoid extra nesting
    async with (
        generation_context(chat_id, user_id, telegram_thread_id) as
        cancel_event,
        DraftManager(
            bot=first_message.bot,
            chat_id=chat_id,
            topic_id=telegram_thread_id,
            keepalive_interval=DRAFT_KEEPALIVE_INTERVAL,
        ) as dm,
    ):
        # StreamingSession encapsulates all streaming state
        # - Display blocks (thinking, text)
        # - Pending tools
        # - Last sent text for deduplication
        stream = StreamingSession(dm, thread_id)

        # Track cumulative output chars across iterations (for partial cost)
        total_output_chars = 0

        for iteration in range(max_iterations):
            logger.info("stream.unified.iteration",
                        thread_id=thread_id,
                        iteration=iteration + 1)

            # Reset per-iteration state (display persists across iterations)
            stream.reset_iteration()

            # Create request for this iteration
            iter_request = LLMRequest(
                messages=[
                    Message(role=msg["role"], content=msg["content"])
                    for msg in conversation
                ],
                system_prompt=request.system_prompt,
                model=request.model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                tools=request.tools,
            )

            # Stream events (DraftManager handles cleanup via context manager)
            # Phase 2.5: Track if cancelled for handling after loop
            was_cancelled = False

            async for event in claude_provider.stream_events(iter_request):
                # Phase 2.5: Check for user cancellation between events
                if cancel_event.is_set():
                    # Determine current phase for logging
                    current_phase = "unknown"
                    if stream.display.total_thinking_length() > 0:
                        if stream.get_final_text():
                            current_phase = "text"
                        else:
                            current_phase = "thinking"
                    elif stream.get_final_text():
                        current_phase = "text"

                    logger.info(
                        "stream.cancelled_by_user",
                        thread_id=thread_id,
                        iteration=iteration + 1,
                        phase=current_phase,
                        thinking_length=stream.display.total_thinking_length(),
                        text_length=len(stream.get_final_text()),
                        pending_tools=len(stream.pending_tools),
                    )
                    was_cancelled = True
                    break

                if event.type == "thinking_delta":
                    await stream.handle_thinking_delta(event.content)

                elif event.type == "text_delta":
                    await stream.handle_text_delta(event.content)

                elif event.type == "tool_use":
                    await stream.handle_tool_use_start(event.tool_id,
                                                       event.tool_name)

                elif event.type == "block_end":
                    if event.tool_name and event.tool_id:
                        # Tool input complete
                        stream.handle_tool_input_complete(
                            event.tool_id, event.tool_name, event.tool_input or
                            {})
                        # Update display with tool marker
                        await stream.update_display()
                    else:
                        await stream.handle_block_end()

                elif event.type == "message_end":
                    stream.handle_message_end(event.stop_reason)

                elif event.type == "stream_complete":
                    stream.handle_stream_complete(event.final_message)

            # Final update for any remaining text
            await stream.update_display()

            # Log iteration stats
            stream.log_iteration_complete(iteration + 1)

            # Accumulate output chars before any clearing (for partial cost)
            total_output_chars += stream.get_current_text_length()

            # Phase 2.5: Handle user cancellation
            if was_cancelled:
                partial_answer = stream.get_final_text()
                partial_display = stream.get_final_display()

                # Add interrupted indicator to display (MarkdownV2 format)
                # In MarkdownV2: _text_ for italic, \[ and \] to escape brackets
                stopped_suffix = "\n\n_\\[interrupted\\]_"
                if partial_display.strip():
                    partial_display = partial_display + stopped_suffix
                else:
                    partial_display = "_\\[interrupted\\]_"

                # Finalize draft with partial content
                final_message = None
                try:
                    final_message = await dm.current.finalize(
                        final_text=partial_display)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("stream.cancelled.finalize_failed",
                                 thread_id=thread_id,
                                 error=str(e))

                # Get thinking chars for partial cost estimate
                thinking_chars = stream.display.total_thinking_length()

                logger.info(
                    "stream.unified.stopped_by_user",
                    thread_id=thread_id,
                    partial_answer_length=len(partial_answer),
                    partial_display_length=len(partial_display),
                    thinking_chars=thinking_chars,
                    finalized=final_message is not None,
                )

                # Return with was_cancelled=True and chars for partial billing
                return (partial_answer, final_message, False, None, True,
                        thinking_chars, total_output_chars)

            if stream.stop_reason in ("end_turn", "pause_turn"):
                # Final answer
                final_answer = stream.get_final_text()
                final_display = stream.get_final_display()

                logger.info("stream.unified.complete",
                            thread_id=thread_id,
                            total_iterations=iteration + 1,
                            final_answer_length=len(final_answer),
                            stop_reason=stream.stop_reason,
                            had_thinking=stream.display.total_thinking_length()
                            > 0)

                # Finalize draft to permanent message
                final_message = None
                if final_display.strip():
                    try:
                        final_message = await dm.current.finalize(
                            final_text=final_display)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error("stream.draft_finalize_failed",
                                     thread_id=thread_id,
                                     error=str(e))
                else:
                    await dm.current.clear()

                # No continuation needed - final answer (chars=0, not used for billing)
                return final_answer, final_message, False, None, False, 0, 0

            if stream.stop_reason == "tool_use" and stream.pending_tools:
                # Execute all tools in PARALLEL, process results AS COMPLETED
                pending_tools = stream.pending_tools
                tool_names = [t.name for t in pending_tools]
                logger.info("stream.unified.executing_tools_parallel",
                            thread_id=thread_id,
                            tool_count=len(pending_tools),
                            tool_names=tool_names)

                # Create indexed tasks for as_completed processing
                async def _indexed_tool_task(idx: int, tool: ToolCall) -> tuple:
                    """Execute tool and return (index, result) for ordering."""
                    result = await execute_single_tool_safe(
                        tool_name=tool.name,
                        tool_input=tool.input,
                        bot=first_message.bot,
                        session=session,
                        thread_id=thread_id,
                        user_id=user_id,
                    )
                    return (idx, result)

                tool_tasks = [
                    _indexed_tool_task(idx, tool)
                    for idx, tool in enumerate(pending_tools)
                ]

                # Process results as they complete (not waiting for all)
                results = [None] * len(pending_tools)  # Preserve order
                first_file_committed = False
                force_turn_break = False  # Phase 3.4: sequential delivery
                turn_break_tool = None

                for coro in asyncio.as_completed(tool_tasks):
                    idx, result = await coro
                    tool = pending_tools[idx]
                    tool_duration = result.get("_duration", 0)
                    is_error = bool(result.get("error"))

                    if not is_error:
                        # Send file immediately when ready
                        # IMPORTANT: process_generated_files adds files_delivered
                        # to result dict, so we must call it BEFORE creating
                        # clean_result
                        # Phase 2.5: Skip file delivery if user cancelled
                        if result.get(
                                "_file_contents") and not cancel_event.is_set():
                            if not first_file_committed:
                                # Commit text BEFORE first file
                                await stream.commit_for_files()
                                first_file_committed = True
                            # Send file immediately
                            await process_generated_files(
                                result, first_message, thread_id, session,
                                user_file_repo, chat_id, user_id,
                                telegram_thread_id)
                        elif result.get(
                                "_file_contents") and cancel_event.is_set():
                            logger.info(
                                "stream.unified.file_skipped_cancelled",
                                thread_id=thread_id,
                                tool_name=tool.name,
                            )

                        # Phase 3.4: Check for sequential delivery
                        if result.get("_force_turn_break"):
                            force_turn_break = True
                            turn_break_tool = tool.name
                            logger.info(
                                "stream.unified.turn_break_requested",
                                thread_id=thread_id,
                                tool_name=tool.name,
                            )

                    # Clean up metadata keys AFTER process_generated_files
                    # so files_delivered is included in tool result
                    clean_result = {
                        k: v for k, v in result.items() if not k.startswith("_")
                    }
                    if is_error:
                        clean_result["error"] = result["error"]

                    if not is_error:
                        # Charge user for tool cost
                        if "cost_usd" in clean_result:
                            await charge_for_tool(session, user_id, tool.name,
                                                  clean_result,
                                                  first_message.message_id)

                        record_tool_call(tool_name=tool.name,
                                         success=True,
                                         duration=tool_duration)
                        if "cost_usd" in clean_result:
                            record_cost(service=tool.name,
                                        amount_usd=float(
                                            clean_result["cost_usd"]))
                    else:
                        record_tool_call(tool_name=tool.name,
                                         success=False,
                                         duration=tool_duration)
                        record_error(error_type="tool_execution",
                                     handler=tool.name)

                    results[idx] = clean_result

                # Convert results list (filled via as_completed)
                raw_results = results

                # Add system messages AFTER files (so they appear after photos)
                for idx, result in enumerate(raw_results):
                    tool = pending_tools[idx]
                    is_error = bool(result.get("error"))

                    if not is_error:
                        clean_result = {
                            k: v
                            for k, v in result.items()
                            if not k.startswith("_")
                        }
                        tool_system_msg = get_tool_system_message(
                            tool.name, tool.input, clean_result)
                        if tool_system_msg:
                            stream.add_system_message(tool_system_msg)

                # Update display after all tools processed
                await stream.update_display()

                # Format tool results
                tool_uses = [{
                    "id": t.tool_id,
                    "name": t.name
                } for t in pending_tools]
                tool_results = format_tool_results(tool_uses, results)

                # Add to conversation using captured message from session
                captured_msg = stream.captured_message
                if captured_msg and captured_msg.content:
                    serialized_content = []
                    for block in captured_msg.content:
                        if hasattr(block, 'model_dump'):
                            serialized_content.append(block.model_dump())
                        else:
                            serialized_content.append(block)
                    conversation.append({
                        "role": "assistant",
                        "content": serialized_content
                    })
                    conversation.append({
                        "role": "user",
                        "content": tool_results
                    })
                else:
                    logger.error("stream.unified.no_assistant_message",
                                 thread_id=thread_id,
                                 tool_count=len(pending_tools))
                    await dm.current.clear()
                    return (
                        "⚠️ Tool execution error: missing assistant context",
                        None, False, None, False, 0, 0)

                # Update display with system messages
                await stream.update_display()

                logger.info("stream.unified.tool_results_added",
                            thread_id=thread_id,
                            tool_count=len(pending_tools))

                # Phase 2.5: Check for cancellation after tool execution
                # User may have pressed /stop while tools were running
                if cancel_event.is_set():
                    logger.info(
                        "stream.cancelled_after_tools",
                        thread_id=thread_id,
                        iteration=iteration + 1,
                        tools_completed=len(pending_tools),
                        tool_names=tool_names,
                    )

                    partial_answer = stream.get_final_text()
                    partial_display = stream.get_final_display()

                    # Add interrupted indicator
                    stopped_suffix = "\n\n_\\[interrupted\\]_"
                    if partial_display.strip():
                        partial_display = partial_display + stopped_suffix
                    else:
                        partial_display = "_\\[interrupted\\]_"

                    # Finalize draft with partial content
                    final_message = None
                    try:
                        final_message = await dm.current.finalize(
                            final_text=partial_display)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(
                            "stream.cancelled_after_tools.finalize_failed",
                            thread_id=thread_id,
                            error=str(e))

                    # Get thinking chars for partial cost estimate
                    thinking_chars = stream.display.total_thinking_length()
                    return (partial_answer, final_message, False, None, True,
                            thinking_chars, total_output_chars)

                # Phase 3.4: Handle sequential delivery turn break
                if force_turn_break:
                    logger.info("stream.unified.forcing_turn_break",
                                thread_id=thread_id,
                                triggered_by=turn_break_tool)

                    # Get current partial answer
                    partial_answer = stream.get_final_text()
                    partial_display = stream.get_final_display()

                    # Finalize current draft
                    final_message = None
                    if partial_display.strip():
                        try:
                            final_message = await dm.current.finalize(
                                final_text=partial_display)
                        except Exception as e:  # pylint: disable=broad-exception-caught
                            logger.error("stream.turn_break.finalize_failed",
                                         thread_id=thread_id,
                                         error=str(e))

                    # Return with continuation needed
                    # Conversation state is passed so caller can continue
                    return (partial_answer, final_message, True, conversation,
                            False, 0, 0)

            else:
                # Unexpected stop reason
                logger.warning("stream.unified.unexpected_stop",
                               thread_id=thread_id,
                               stop_reason=stream.stop_reason)

                final_answer = stream.get_final_text()
                if not final_answer:
                    final_answer = f"⚠️ Unexpected stop: {stream.stop_reason}"

                final_display = stream.get_final_display()
                if final_display:
                    await dm.current.update(final_display, force=True)
                else:
                    await dm.current.update(escape_html(
                        f"⚠️ Unexpected stop: {stream.stop_reason}"),
                                            force=True)

                # Finalize draft
                try:
                    final_message = await dm.current.finalize()
                except Exception:  # pylint: disable=broad-exception-caught
                    final_message = None

                return final_answer, final_message, False, None, False, 0, 0

        # Max iterations exceeded (DraftManager will cleanup on exit)
        logger.error("stream.unified.max_iterations",
                     thread_id=thread_id,
                     max_iterations=max_iterations)

        error_msg = (
            f"⚠️ Tool loop exceeded maximum iterations ({max_iterations}). "
            "The task might be too complex.")

        # Finalize draft with error message
        try:
            await dm.current.update(error_msg)
            final_message = await dm.current.finalize()
        except Exception:  # pylint: disable=broad-exception-caught
            final_message = None

        return error_msg, final_message, False, None, False, 0, 0


async def _send_with_retry(
    message: types.Message,
    text: str,
    max_retries: int = 3,
    parse_mode: str | None = "HTML",
) -> types.Message:
    """Send message with retry on flood control.

    Args:
        message: Message to reply to.
        text: Text to send.
        max_retries: Maximum retry attempts.
        parse_mode: Parse mode for the message.

    Returns:
        Sent message.

    Raises:
        TelegramRetryAfter: If all retries exhausted.
    """
    for attempt in range(max_retries):
        try:
            return await message.answer(text, parse_mode=parse_mode)
        except TelegramRetryAfter as e:
            if attempt == max_retries - 1:
                raise
            logger.warning("telegram.flood_control",
                           retry_after=e.retry_after,
                           attempt=attempt + 1)
            await asyncio.sleep(e.retry_after)
    raise TelegramRetryAfter(retry_after=0,
                             method="send_with_retry",
                             message="Max retries")


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# pylint: disable=too-many-return-statements
async def _process_message_batch(thread_id: int,
                                 messages: list['ProcessedMessage']) -> None:
    """Process batch of messages for a thread.

    This function is called by the unified pipeline when a batch is ready.
    Creates its own database session and handles the complete flow from
    saving messages to streaming Claude response.

    Args:
        thread_id: Database thread ID.
        messages: List of ProcessedMessage objects (all I/O complete).
    """
    # Start timing for total request
    total_request_start = time.perf_counter()

    if not messages:
        logger.warning("claude_handler.empty_batch", thread_id=thread_id)
        return

    if claude_provider is None:
        logger.error("claude_handler.provider_not_initialized")
        # Send error to first message
        await messages[0].original_message.answer(
            "Bot is not properly configured. Please contact administrator.")
        return

    # Use first message for bot/chat context
    first_message = messages[0].original_message

    # Calculate content lengths for logging
    content_lengths = []
    for processed in messages:
        if processed.transcript:
            content_lengths.append(len(processed.transcript.text))
        elif processed.text:
            content_lengths.append(len(processed.text))
        else:
            content_lengths.append(0)

    logger.info("claude_handler.batch_received",
                thread_id=thread_id,
                batch_size=len(messages),
                content_lengths=content_lengths,
                has_media=[p.has_media for p in messages],
                telegram_thread_id=first_message.message_thread_id)

    # Record batch metrics (Phase 3.1: Prometheus)
    if len(messages) > 1:
        record_messages_batched(len(messages))

    try:
        # Create new database session for this batch
        async with get_session() as session:
            # 1. Get thread (to retrieve user_id, chat_id, model_id)
            thread_repo = ThreadRepository(session)
            thread = await thread_repo.get_by_id(thread_id)

            if not thread:
                logger.error("claude_handler.thread_not_found",
                             thread_id=thread_id)
                await first_message.answer(
                    "Thread not found. Please contact administrator.")
                return

            # 2. Save all messages to database
            msg_repo = MessageRepository(session)
            for processed in messages:
                message = processed.original_message

                # Determine text_content based on ProcessedMessage type
                if processed.transcript:
                    # Voice/Video note: use transcript with prefix
                    text_content = processed.get_text_for_db()
                elif processed.files:
                    # File: use caption or generate file mention
                    if processed.text:
                        text_content = processed.text
                    else:
                        # Generate file mention
                        file = processed.files[0]
                        text_content = (
                            f"📎 User uploaded {file.file_type.value}: "
                            f"{file.filename} ({file.size_bytes} bytes) "
                            f"[file_id: {file.claude_file_id}]")
                else:
                    # Regular text message
                    text_content = processed.text or ""

                # Extract context from Telegram message (replies, quotes, forwards)
                msg_context = extract_message_context(message)

                await msg_repo.create_message(
                    chat_id=thread.chat_id,
                    message_id=message.message_id,
                    thread_id=thread_id,
                    from_user_id=thread.user_id,
                    date=message.date.timestamp(),
                    role=MessageRole.USER,
                    text_content=text_content,
                    reply_to_message_id=message.reply_to_message.message_id
                    if message.reply_to_message else None,
                    # Context fields (Telegram features)
                    sender_display=msg_context.sender_display,
                    forward_origin=msg_context.forward_origin,
                    reply_snippet=msg_context.reply_snippet,
                    reply_sender_display=msg_context.reply_sender_display,
                    quote_data=msg_context.quote_data,
                )

            await session.commit()

            logger.debug("claude_handler.batch_messages_saved",
                         thread_id=thread_id,
                         batch_size=len(messages))

            # 3. Get user for model config and custom prompt
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(thread.user_id)

            if not user:
                logger.error("claude_handler.user_not_found",
                             user_id=thread.user_id)
                await first_message.answer(
                    "User not found. Please contact administrator.")
                return

            # 3.5. Get available files for this thread (Phase 1.5)
            # Unified file architecture: fetch both delivered and pending files
            logger.debug("claude_handler.creating_file_repo",
                         thread_id=thread_id)
            user_file_repo = UserFileRepository(session)

            # Get delivered files from database
            logger.debug("claude_handler.calling_get_available_files",
                         thread_id=thread_id,
                         repo_type=type(user_file_repo).__name__)
            available_files = await get_available_files(thread_id,
                                                        user_file_repo)

            # Get pending files from exec_cache (not yet delivered)
            pending_files = await get_pending_files_for_thread(thread_id)

            logger.info("claude_handler.files_retrieved",
                        thread_id=thread_id,
                        delivered_count=len(available_files),
                        pending_count=len(pending_files))

            # 4. Get thread history (includes newly saved messages)
            # Limit to 500 most recent messages for performance
            # Context manager will trim based on token budget
            history = await msg_repo.get_thread_messages(thread_id, limit=500)

            logger.debug("claude_handler.history_retrieved",
                         thread_id=thread_id,
                         message_count=len(history))

            # 5. Build context
            context_mgr = ContextManager(claude_provider)

            # Get model config from user
            model_config = get_model(user.model_id)

            logger.debug("claude_handler.using_model",
                         model_id=user.model_id,
                         model_name=model_config.display_name)

            # Unified file architecture: Generate files section for system prompt
            # Includes both delivered files (from DB) and pending files (from cache)
            files_section = format_unified_files_section(
                available_files, pending_files) if (available_files or
                                                    pending_files) else None

            # Compose 3-level system prompt with multi-block caching
            # GLOBAL (cached) + user custom (cached if large) + files (NOT cached)
            system_prompt_blocks = compose_system_prompt_blocks(
                global_prompt=GLOBAL_SYSTEM_PROMPT,
                custom_prompt=user.custom_prompt,
                files_context=files_section)

            # Calculate total length for logging
            total_prompt_length = sum(
                len(block.get("text", "")) for block in system_prompt_blocks)

            logger.info("claude_handler.system_prompt_composed",
                        thread_id=thread_id,
                        telegram_thread_id=thread.thread_id,
                        has_custom_prompt=user.custom_prompt is not None,
                        has_files_context=files_section is not None,
                        delivered_files=len(available_files),
                        pending_files=len(pending_files),
                        block_count=len(system_prompt_blocks),
                        total_length=total_prompt_length)

            # Convert DB messages to LLM messages with context formatting
            # Uses ContextFormatter to include reply/quote/forward context
            # Phase 2: Uses async format to include multimodal content (images, PDFs)
            formatter = ContextFormatter(chat_type=first_message.chat.type)
            llm_messages = await formatter.format_conversation_with_files(
                history, session)

            # Build context using total prompt length for token estimation
            context = await context_mgr.build_context(
                messages=llm_messages,
                model_context_window=model_config.context_window,
                system_prompt=total_prompt_length,  # Pass length for estimation
                max_output_tokens=model_config.max_output,
                buffer_percent=CLAUDE_TOKEN_BUFFER_PERCENT)

            logger.info("claude_handler.context_built",
                        thread_id=thread_id,
                        included_messages=len(context),
                        total_messages=len(llm_messages))

            # 6. Prepare Claude request with multi-block cached system prompt
            # GLOBAL (cached) + user custom (cached if large) + files (NOT cached)
            request = LLMRequest(
                messages=context,
                system_prompt=
                system_prompt_blocks,  # Multi-block for optimal caching
                model=user.model_id,
                max_tokens=model_config.max_output,
                temperature=config.CLAUDE_TEMPERATURE,
                tools=get_tool_definitions())  # Always pass tools

            logger.info("claude_handler.request_prepared",
                        thread_id=thread_id,
                        has_tools=request.tools is not None,
                        tool_count=len(request.tools) if request.tools else 0)

            # 7. Show typing indicator (only when starting processing)
            await first_message.bot.send_chat_action(first_message.chat.id,
                                                     "typing")

            # Start timing for response metrics
            request_start_time = time.perf_counter()

            # 8. Unified streaming with thinking/text/tools
            # All requests go through stream_events for real-time updates
            # Phase 3.4: Supports continuation for sequential file delivery
            logger.info("claude_handler.unified_streaming",
                        thread_id=thread_id,
                        tool_count=len(request.tools) if request.tools else 0)

            try:
                # Phase 3.4: Continuation loop for sequential file delivery
                # Max 5 continuations to prevent infinite loops
                max_continuations = 5
                continuation_conversation = None
                all_response_parts = []
                final_bot_message = None

                was_cancelled = False  # Track if user cancelled generation
                thinking_chars = 0  # Track thinking chars for partial payment
                output_chars = 0  # Track output chars for partial payment
                for continuation_idx in range(max_continuations + 1):
                    (response_text, bot_message, needs_continuation,
                     conversation_state, was_cancelled, iter_thinking_chars,
                     iter_output_chars) = await _stream_with_unified_events(
                         request=request,
                         first_message=first_message,
                         thread_id=thread_id,
                         session=session,
                         user_file_repo=user_file_repo,
                         chat_id=thread.chat_id,
                         user_id=thread.user_id,
                         telegram_thread_id=thread.thread_id,
                         continuation_conversation=continuation_conversation,
                     )

                    # Accumulate chars across iterations for partial billing
                    thinking_chars += iter_thinking_chars
                    output_chars += iter_output_chars

                    # Collect response parts
                    if response_text:
                        all_response_parts.append(response_text)

                    # Keep track of latest message for DB
                    if bot_message:
                        final_bot_message = bot_message

                    if not needs_continuation:
                        # Normal completion
                        break

                    # Continuation needed (sequential delivery)
                    logger.info("claude_handler.continuation",
                                thread_id=thread_id,
                                continuation_idx=continuation_idx + 1,
                                max_continuations=max_continuations)

                    continuation_conversation = conversation_state

                else:
                    # Max continuations reached (typically from many sequential
                    # deliver_file calls). This is not an error - files were
                    # delivered, just more than expected.
                    logger.info("claude_handler.max_continuations_reached",
                                thread_id=thread_id,
                                max_continuations=max_continuations,
                                response_parts_count=len(all_response_parts))

                # Combine all response parts
                response_text = "\n\n".join(all_response_parts)
                bot_message = final_bot_message

                # With sendMessageDraft, final message is already sent via finalize()
                # No cleanup needed - drafts don't create intermediate messages

                # Strip tool markers for database storage
                clean_response = _strip_tool_markers(
                    response_text) if response_text else ""

                # If finalize failed, send fallback message
                if not bot_message:
                    if clean_response:
                        safe_final = escape_html(clean_response)
                        chunks = split_text_smart(safe_final)
                        for chunk in chunks:
                            bot_message = await _send_with_retry(
                                first_message, chunk)
                    elif all_response_parts:
                        # Had content in previous continuations but empty final
                        # This can happen with many sequential deliveries
                        logger.debug("claude_handler.continuations_exhausted",
                                     thread_id=thread_id)
                        # Files were already delivered, just acknowledge
                        bot_message = await _send_with_retry(
                            first_message, "✓ Files delivered.")
                    else:
                        logger.warning("claude_handler.empty_response",
                                       thread_id=thread_id)
                        bot_message = await _send_with_retry(
                            first_message,
                            "⚠️ Claude returned an empty response. "
                            "Please try rephrasing your message.")

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("claude_handler.streaming_failed",
                             thread_id=thread_id,
                             error=str(e),
                             exc_info=True)
                bot_message = await first_message.answer(
                    "⚠️ An error occurred. Please try again.")
                return

            # Check bot_message exists
            if not bot_message:
                logger.error("claude_handler.no_bot_message",
                             thread_id=thread_id)
                await first_message.answer("Failed to send response.")
                return

            # Phase 2.5.2: Partial payment for cancelled requests
            # Estimate cost from accumulated text and charge user
            if was_cancelled:
                # Estimate tokens from accumulated chars (~4 chars per token)
                # output_chars accumulated from _stream_with_unified_events
                estimated_output_tokens = output_chars // 4
                estimated_thinking_tokens = thinking_chars // 4

                # Estimate input tokens from context
                # (system prompt + messages sent to Claude)
                context_chars = total_prompt_length
                for msg in context:
                    if isinstance(msg.content, str):
                        context_chars += len(msg.content)
                    elif isinstance(msg.content, list):
                        for block in msg.content:
                            if hasattr(block, 'text'):
                                context_chars += len(block.text)
                estimated_input_tokens = context_chars // 4

                # Calculate partial cost with cache assumption
                # System prompt is likely cached (multi-block), use cache pricing
                system_prompt_tokens = total_prompt_length // 4
                user_context_tokens = max(
                    0, estimated_input_tokens - system_prompt_tokens)

                # Cache read pricing for system prompt (10x cheaper)
                cache_pricing = (model_config.pricing_cache_read or
                                 model_config.pricing_input * 0.1)

                partial_cost = (
                    (system_prompt_tokens / 1_000_000) * cache_pricing +
                    (user_context_tokens / 1_000_000) *
                    model_config.pricing_input +
                    ((estimated_output_tokens + estimated_thinking_tokens) /
                     1_000_000) * model_config.pricing_output)

                logger.info(
                    "claude_handler.cancelled_partial_charge",
                    thread_id=thread_id,
                    system_prompt_tokens=system_prompt_tokens,
                    user_context_tokens=user_context_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                    estimated_thinking_tokens=estimated_thinking_tokens,
                    output_chars=output_chars,
                    thinking_chars=thinking_chars,
                    partial_cost_usd=round(partial_cost, 6),
                )

                # Charge user for partial usage (tools already charged separately)
                if partial_cost > 0:
                    try:
                        balance_op_repo = BalanceOperationRepository(session)
                        balance_service = BalanceService(
                            session, user_repo, balance_op_repo)

                        balance_after = await balance_service.charge_user(
                            user_id=user.id,
                            amount=partial_cost,
                            description=(
                                f"Claude API (cancelled): "
                                f"~{estimated_input_tokens} input + "
                                f"~{estimated_output_tokens} output + "
                                f"~{estimated_thinking_tokens} thinking tokens"
                            ),
                            related_message_id=(bot_message.message_id
                                                if bot_message else None),
                        )

                        logger.info(
                            "claude_handler.cancelled_user_charged",
                            user_id=user.id,
                            partial_cost_usd=round(partial_cost, 6),
                            balance_after=float(balance_after),
                        )

                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(
                            "claude_handler.cancelled_charge_error",
                            user_id=user.id,
                            partial_cost_usd=round(partial_cost, 6),
                            error=str(e),
                            exc_info=True,
                        )

                # Record metrics for cancelled request
                record_claude_request(model=user.model_id, success=True)
                record_cost(service="claude_cancelled", amount_usd=partial_cost)

                return

            # 9. Get usage stats, stop_reason, thinking, and calculate cost
            usage = await claude_provider.get_usage()
            stop_reason = claude_provider.get_stop_reason()
            # Phase 1.4.3: Get thinking blocks with signatures for DB storage
            # (required for Extended Thinking - API needs signatures in context)
            thinking_blocks_json = claude_provider.get_thinking_blocks_json()

            # Calculate Claude API cost
            cost_usd = (
                (usage.input_tokens / 1_000_000) * model_config.pricing_input +
                ((usage.output_tokens + usage.thinking_tokens) / 1_000_000) *
                model_config.pricing_output)

            # Calculate web_search cost ($0.01 per search request)
            web_search_cost = usage.web_search_requests * 0.01
            if web_search_cost > 0:
                cost_usd += web_search_cost
                logger.info(
                    "tools.web_search.user_charged",
                    user_id=user.id,
                    web_search_requests=usage.web_search_requests,
                    cost_usd=web_search_cost,
                )
                # Record each web_search as a tool call for metrics
                for _ in range(usage.web_search_requests):
                    record_tool_call(tool_name="web_search",
                                     success=True,
                                     duration=0.0)
                record_cost(service="web_search", amount_usd=web_search_cost)

            # Record response time (Claude API duration)
            response_duration = time.perf_counter() - request_start_time
            claude_api_ms = response_duration * 1000

            # Calculate total request time (from handler start to response complete)
            total_request_ms = (time.perf_counter() -
                                total_request_start) * 1000

            logger.info("claude_handler.response_complete",
                        thread_id=thread_id,
                        model_id=user.model_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        thinking_tokens=usage.thinking_tokens,
                        cache_read_tokens=usage.cache_read_tokens,
                        cost_usd=round(cost_usd, 6),
                        response_length=len(response_text),
                        stop_reason=stop_reason,
                        claude_api_ms=round(claude_api_ms, 2),
                        total_request_ms=round(total_request_ms, 2))

            # Record Prometheus metrics
            record_claude_request(model=user.model_id, success=True)
            record_claude_tokens(
                model=user.model_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_creation_tokens,
            )
            record_cost(service="claude", amount_usd=cost_usd)
            record_message_sent(chat_type=first_message.chat.type)

            # Record response time for Prometheus
            record_claude_response_time(model=user.model_id,
                                        seconds=response_duration)

            # Record cache metrics (Phase 3.1: Prometheus)
            if usage.cache_read_tokens and usage.cache_read_tokens > 0:
                record_cache_hit(tokens_saved=usage.cache_read_tokens)
            if usage.cache_creation_tokens and usage.cache_creation_tokens > 0:
                record_cache_miss()

            # Phase 1.4.4: Handle special stop reasons
            if stop_reason == "model_context_window_exceeded":
                logger.warning("claude_handler.context_overflow",
                               thread_id=thread_id,
                               input_tokens=usage.input_tokens,
                               context_window=model_config.context_window)

                # Add warning message to user
                warning_msg = (
                    "\n\n⚠️ **Context window exceeded**\n\n"
                    f"The conversation has exceeded the {model_config.context_window:,} "
                    f"token limit for {model_config.display_name}. "
                    "Consider starting a new thread or switching to a model with a larger "
                    "context window.")
                response_text += warning_msg

                # Update bot message with warning
                if bot_message:
                    try:
                        await bot_message.edit_text(response_text)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.warning("claude_handler.warning_edit_failed",
                                       error=str(e))

            elif stop_reason == "refusal":
                logger.warning("claude_handler.refusal", thread_id=thread_id)

                # Add explanation to user
                refusal_msg = (
                    "\n\n⚠️ **Response refused**\n\n"
                    "Claude declined to provide a response to your request. "
                    "This typically happens when the request violates usage policies. "
                    "Please rephrase your question or request.")
                response_text += refusal_msg

                # Update bot message with explanation
                if bot_message:
                    try:
                        await bot_message.edit_text(response_text)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.warning("claude_handler.refusal_edit_failed",
                                       error=str(e))

            elif stop_reason == "max_tokens":
                logger.info("claude_handler.max_tokens_reached",
                            thread_id=thread_id,
                            max_tokens=config.CLAUDE_MAX_TOKENS)

            # 10. Save Claude response via write-behind (Phase 3.3)
            # Queue message write + token usage for background DB flush
            total_tokens = usage.input_tokens + usage.output_tokens
            if usage.thinking_tokens:
                total_tokens += usage.thinking_tokens

            message_data = {
                "chat_id": thread.chat_id,
                "message_id": bot_message.message_id,
                "thread_id": thread_id,
                "from_user_id": None,  # Bot message
                "date": bot_message.date.isoformat(),
                "role": MessageRole.ASSISTANT.value,
                "text_content": response_text,
                "thinking_blocks": thinking_blocks_json,
                # Token usage included in message data
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_creation_tokens,
                "thinking_tokens": usage.thinking_tokens,
                "cost_usd": float(cost_usd),
                "model_id": user.model_id,
            }

            queued = await queue_write(WriteType.MESSAGE, message_data)
            if not queued:
                # Fallback to direct DB write if Redis unavailable
                logger.warning("claude_handler.write_behind_fallback",
                               thread_id=thread_id,
                               reason="redis_unavailable")
                await msg_repo.create_message(
                    chat_id=thread.chat_id,
                    message_id=bot_message.message_id,
                    thread_id=thread_id,
                    from_user_id=None,
                    date=bot_message.date.timestamp(),
                    role=MessageRole.ASSISTANT,
                    text_content=response_text,
                    thinking_blocks=thinking_blocks_json,
                )
                await msg_repo.add_tokens(
                    chat_id=thread.chat_id,
                    message_id=bot_message.message_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_tokens=usage.cache_creation_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    thinking_tokens=usage.thinking_tokens,
                )

            # 11. Queue user stats update via write-behind (Phase 3.3)
            stats_data = {
                "user_id": user.id,
                "messages": len(messages),
                "tokens": total_tokens,
            }
            stats_queued = await queue_write(WriteType.USER_STATS, stats_data)
            if not stats_queued:
                # Fallback to direct DB write
                await user_repo.increment_stats(
                    telegram_id=user.id,
                    messages=len(messages),
                    tokens=total_tokens,
                )

            # 12. Invalidate message cache (next read fetches from DB)
            # This ensures consistency until full cache-first is implemented
            await invalidate_messages(thread_id)

            # Commit any pending direct writes (fallback path)
            await session.commit()

            # Phase 2.1: Charge user for API usage
            try:
                balance_op_repo = BalanceOperationRepository(session)
                balance_service = BalanceService(session, user_repo,
                                                 balance_op_repo)

                # Charge user for actual cost
                balance_after = await balance_service.charge_user(
                    user_id=user.id,
                    amount=cost_usd,
                    description=(
                        f"Claude API call: {usage.input_tokens} input + "
                        f"{usage.output_tokens} output + "
                        f"{usage.thinking_tokens} thinking tokens, "
                        f"model {model_config.display_name}"),
                    related_message_id=bot_message.message_id,
                )

                logger.info(
                    "claude_handler.user_charged",
                    user_id=user.id,
                    model_id=user.model_id,
                    cost_usd=round(cost_usd, 6),
                    balance_after=float(balance_after),
                    thread_id=thread_id,
                    message_id=bot_message.message_id,
                )

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "claude_handler.charge_user_error",
                    user_id=user.id,
                    cost_usd=round(cost_usd, 6),
                    error=str(e),
                    exc_info=True,
                    msg="CRITICAL: Failed to charge user for API usage!",
                )
                # Don't fail the request - user already got response

            logger.info("claude_handler.bot_message_saved",
                        thread_id=thread_id,
                        message_id=bot_message.message_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens)

    except ContextWindowExceededError as e:
        logger.error("claude_handler.context_exceeded",
                     thread_id=thread_id,
                     tokens_used=e.tokens_used,
                     tokens_limit=e.tokens_limit,
                     exc_info=True)
        record_error(error_type="context_exceeded", handler="claude")

        await first_message.answer(
            f"⚠️ Context window exceeded.\n\n"
            f"Your conversation is too long ({e.tokens_used:,} tokens). "
            f"Please start a new thread or reduce message history.")

    except RateLimitError as e:
        logger.error("claude_handler.rate_limit",
                     thread_id=thread_id,
                     error=str(e),
                     retry_after=e.retry_after,
                     exc_info=True)
        record_error(error_type="rate_limit", handler="claude")
        record_claude_request(model="unknown", success=False)

        retry_msg = ""
        if e.retry_after:
            retry_msg = f"\n\nPlease try again in {e.retry_after} seconds."

        await first_message.answer(
            f"⚠️ Rate limit exceeded.{retry_msg}\n\n"
            f"Too many requests. Please wait a moment and try again.")

    except APIConnectionError as e:
        logger.error("claude_handler.connection_error",
                     thread_id=thread_id,
                     error=str(e),
                     exc_info=True)
        record_error(error_type="connection_error", handler="claude")
        record_claude_request(model="unknown", success=False)

        await first_message.answer(
            "⚠️ Connection error.\n\n"
            "Failed to connect to Claude API. Please check your internet "
            "connection and try again.")

    except APITimeoutError as e:
        logger.error("claude_handler.timeout",
                     thread_id=thread_id,
                     error=str(e),
                     exc_info=True)
        record_error(error_type="timeout", handler="claude")
        record_claude_request(model="unknown", success=False)

        await first_message.answer(
            "⚠️ Request timed out.\n\n"
            "The request took too long. Please try again with a shorter "
            "message or simpler question.")

    except LLMError as e:
        logger.error("claude_handler.llm_error",
                     thread_id=thread_id,
                     error=str(e),
                     error_type=type(e).__name__,
                     exc_info=True)
        record_error(error_type="llm_error", handler="claude")
        record_claude_request(model="unknown", success=False)

        await first_message.answer(
            f"⚠️ Error: {str(e)}\n\n"
            f"Please try again or contact administrator if the problem "
            f"persists.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("claude_handler.unexpected_error",
                     thread_id=thread_id,
                     error=str(e),
                     error_type=type(e).__name__,
                     exc_info=True)
        record_error(error_type="unexpected", handler="claude")

        await first_message.answer("⚠️ Unexpected error occurred.\n\n"
                                   "Please try again or contact administrator.")
