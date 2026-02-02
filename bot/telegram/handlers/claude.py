"""Claude conversation processing.

This module provides the core Claude API integration:
- ClaudeProvider initialization
- Message batch processing (_process_message_batch)
- Streaming via StreamingOrchestrator (telegram.streaming.orchestrator)
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
from cache.thread_cache import cache_messages
from cache.thread_cache import get_cached_messages
from cache.thread_cache import invalidate_messages
from cache.thread_cache import update_cached_messages
from cache.user_cache import cache_user
from cache.user_cache import get_cached_user
from cache.user_cache import update_cached_balance
from cache.write_behind import queue_write
from cache.write_behind import WriteType
import config
from config import CLAUDE_TOKEN_BUFFER_PERCENT
from config import FILES_API_TTL_HOURS
from config import get_model
from config import GLOBAL_SYSTEM_PROMPT
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
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_file_repository import UserFileRepository
from services.factory import ServiceFactory
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.concurrency_limiter import concurrency_context
from telegram.concurrency_limiter import ConcurrencyLimitExceeded
from telegram.context.extractors import extract_message_context
from telegram.context.formatter import ContextFormatter
from telegram.handlers.claude_files import process_generated_files
from telegram.handlers.claude_helpers import compose_system_prompt_blocks
from telegram.handlers.claude_helpers import split_text_smart
from telegram.streaming.formatting import escape_html
from telegram.streaming.formatting import \
    strip_tool_markers as _strip_tool_markers
from telegram.streaming.orchestrator import StreamingOrchestrator
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
    logger.debug("claude_handler.provider_initialized")


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
    if not messages:
        # Should never happen - indicates bug in batching logic
        logger.error("claude_handler.empty_batch", thread_id=thread_id)
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

    # Extract user_id from first message for concurrency limiting
    # Done before DB session to avoid holding connection while waiting in queue
    user_id_for_limit = messages[0].metadata.user_id

    # Acquire concurrency slot (may block if user has too many active generations)
    # This is outside the main try to handle ConcurrencyLimitExceeded separately
    try:
        async with concurrency_context(user_id_for_limit,
                                       thread_id) as queue_pos:
            if queue_pos > 0:
                logger.info(
                    "claude_handler.waited_in_queue",
                    user_id=user_id_for_limit,
                    thread_id=thread_id,
                    queue_position=queue_pos,
                )

            # Main processing inside concurrency context
            await _process_batch_with_session(
                thread_id=thread_id,
                messages=messages,
                first_message=first_message,
            )

    except ConcurrencyLimitExceeded as e:
        logger.warning(
            "claude_handler.concurrency_limit_exceeded",
            thread_id=thread_id,
            user_id=e.user_id,
            queue_position=e.queue_position,
            wait_time=round(e.wait_time, 2),
        )
        record_error(error_type="concurrency_limit", handler="claude")

        await first_message.answer(
            f"⚠️ Too many requests.\n\n"
            f"You have too many pending messages. "
            f"Please wait for current generations to complete.\n\n"
            f"Queue position: {e.queue_position}, waited: {e.wait_time:.0f}s")


async def _process_batch_with_session(
    thread_id: int,
    messages: list['ProcessedMessage'],
    first_message: types.Message,
) -> None:
    """Process batch with database session.

    Extracted from _process_message_batch to allow clean concurrency wrapping.
    Contains all the main processing logic.

    Args:
        thread_id: Database thread ID.
        messages: List of ProcessedMessage objects.
        first_message: First Telegram message for replies.
    """
    # Start timing for total request
    total_request_start = time.perf_counter()

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
                    media_group_id=message.media_group_id,
                    # Context fields (Telegram features)
                    sender_display=msg_context.sender_display,
                    forward_origin=msg_context.forward_origin,
                    reply_snippet=msg_context.reply_snippet,
                    reply_sender_display=msg_context.reply_sender_display,
                    quote_data=msg_context.quote_data,
                )

            await session.commit()

            # Invalidate message cache after saving user messages
            # This ensures next read gets fresh data including new messages
            await invalidate_messages(thread_id)

            logger.debug("claude_handler.batch_messages_saved",
                         thread_id=thread_id,
                         batch_size=len(messages))

            # 3. Get user for model config and custom prompt (cache-first)
            services = ServiceFactory(session)
            user = None  # Will be loaded from DB if cache miss
            user_id = thread.user_id  # Telegram user ID

            # Try cache first (Phase 3.3: Cache-First pattern)
            cached_user = await get_cached_user(user_id)

            if cached_user:
                # Cache hit - use cached data
                user_model_id = cached_user["model_id"]
                user_custom_prompt = cached_user.get("custom_prompt")
                logger.debug("claude_handler.user_cache_hit",
                             user_id=user_id,
                             model_id=user_model_id)
            else:
                # Cache miss - load from DB and cache
                user = await services.users.get_by_id(user_id)

                if not user:
                    logger.error("claude_handler.user_not_found",
                                 user_id=user_id)
                    await first_message.answer(
                        "User not found. Please contact administrator.")
                    return

                # Extract values from user object
                user_model_id = user.model_id
                user_custom_prompt = user.custom_prompt

                # Cache user data for next request
                await cache_user(
                    user_id=user_id,
                    balance=user.balance,
                    model_id=user_model_id,
                    first_name=user.first_name,
                    username=user.username,
                    language_code=user.language_code,
                    custom_prompt=user_custom_prompt,
                )

                logger.debug("claude_handler.user_cache_miss",
                             user_id=user_id,
                             model_id=user_model_id)

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
            # Note: We always read from DB after saving user messages
            # (cache was invalidated above to ensure fresh data)
            history = await msg_repo.get_thread_messages(thread_id, limit=500)

            # Cache history for potential future requests in same thread
            # (e.g., rapid follow-up messages, tool continuations)
            history_for_cache = [{
                "role": msg.role.value,
                "text_content": msg.text_content,
                "message_id": msg.message_id,
                "date": msg.date,
            } for msg in history]
            await cache_messages(thread_id, history_for_cache)

            logger.debug("claude_handler.history_retrieved",
                         thread_id=thread_id,
                         message_count=len(history))

            # 5. Build context
            context_mgr = ContextManager(claude_provider)

            # Get model config from user
            model_config = get_model(user_model_id)

            logger.debug("claude_handler.using_model",
                         model_id=user_model_id,
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
                custom_prompt=user_custom_prompt,
                files_context=files_section)

            # Calculate total length for logging
            total_prompt_length = sum(
                len(block.get("text", "")) for block in system_prompt_blocks)

            logger.info("claude_handler.system_prompt_composed",
                        thread_id=thread_id,
                        telegram_thread_id=thread.thread_id,
                        has_custom_prompt=user_custom_prompt is not None,
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
                model=user_model_id,
                max_tokens=model_config.max_output,
                temperature=config.CLAUDE_TEMPERATURE,
                tools=get_tool_definitions())  # Always pass tools

            logger.info("claude_handler.request_prepared",
                        thread_id=thread_id,
                        has_tools=request.tools is not None,
                        tool_count=len(request.tools) if request.tools else 0)

            # 7. Show typing indicator (only when starting processing)
            # StreamingOrchestrator will maintain the indicator during streaming,
            # but we send initial one here for immediate user feedback
            from telegram.chat_action.legacy import send_action
            await send_action(first_message.bot, first_message.chat.id,
                              "typing", thread.thread_id)

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
                any_files_delivered = False  # Track if files delivered across continuations
                for continuation_idx in range(max_continuations + 1):
                    # Use StreamingOrchestrator for cleaner streaming flow
                    orchestrator = StreamingOrchestrator(
                        request=request,
                        first_message=first_message,
                        thread_id=thread_id,
                        session=session,
                        user_file_repo=user_file_repo,
                        chat_id=thread.chat_id,
                        user_id=thread.user_id,
                        telegram_thread_id=thread.thread_id,
                        continuation_conversation=continuation_conversation,
                        claude_provider=claude_provider,
                    )
                    result = await orchestrator.stream()

                    # Extract values from StreamResult
                    response_text = result.text
                    bot_message = result.message
                    needs_continuation = result.needs_continuation
                    conversation_state = result.conversation
                    was_cancelled = result.was_cancelled

                    # Accumulate chars across iterations for partial billing
                    thinking_chars += result.thinking_chars
                    output_chars += result.output_chars

                    # Track file deliveries across continuations
                    if result.has_delivered_files:
                        any_files_delivered = True

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
                    elif (all_response_parts or result.has_sent_parts or
                          any_files_delivered):
                        # Had content in previous continuations, split parts,
                        # or files delivered via deliver_file tool
                        logger.debug(
                            "claude_handler.continuations_exhausted",
                            thread_id=thread_id,
                            all_response_parts=bool(all_response_parts),
                            has_sent_parts=result.has_sent_parts,
                            any_files_delivered=any_files_delivered)
                        # Content was already delivered, just acknowledge
                        bot_message = await _send_with_retry(
                            first_message, "✓ Response delivered.")
                    else:
                        # External API returned empty - this shouldn't happen
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
                # output_chars accumulated from StreamingOrchestrator
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
                        balance_after = await services.balance.charge_user(
                            user_id=user_id,
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
                            user_id=user_id,
                            cost_usd=round(partial_cost, 6),
                            balance_after=float(balance_after),
                        )

                        # Update cached balance (Phase 3.3: Cache-First)
                        await update_cached_balance(user_id, balance_after)

                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(
                            "claude_handler.cancelled_charge_error",
                            user_id=user_id,
                            partial_cost_usd=round(partial_cost, 6),
                            error=str(e),
                            exc_info=True,
                        )

                # Record metrics for cancelled request
                record_claude_request(model=user_model_id, success=True)
                record_cost(service="claude_cancelled", amount_usd=partial_cost)

                return

            # 9. Get usage stats, stop_reason, thinking, and calculate cost
            usage = await claude_provider.get_usage()
            stop_reason = claude_provider.get_stop_reason()
            # Phase 1.4.3: Get thinking blocks with signatures for DB storage
            # (required for Extended Thinking - API needs signatures in context)
            thinking_blocks_json = claude_provider.get_thinking_blocks_json()

            # Calculate Claude API cost (including cache tokens!)
            # See: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#pricing
            # - input_tokens: tokens after last cache breakpoint (full price)
            # - cache_read_tokens: tokens read from cache (0.1x input price)
            # - cache_creation_tokens: tokens written to cache (1.25x input price)
            cache_read_cost = 0.0
            cache_creation_cost = 0.0

            if usage.cache_read_tokens and model_config.pricing_cache_read:
                cache_read_cost = ((usage.cache_read_tokens / 1_000_000) *
                                   model_config.pricing_cache_read)

            # Use 1h cache pricing since GLOBAL_SYSTEM_PROMPT uses 1h TTL
            if usage.cache_creation_tokens and model_config.pricing_cache_write_1h:
                cache_creation_cost = (
                    (usage.cache_creation_tokens / 1_000_000) *
                    model_config.pricing_cache_write_1h)

            cost_usd = (
                (usage.input_tokens / 1_000_000) * model_config.pricing_input +
                cache_read_cost + cache_creation_cost +
                ((usage.output_tokens + usage.thinking_tokens) / 1_000_000) *
                model_config.pricing_output)

            # Calculate web_search cost ($0.01 per search request)
            web_search_cost = usage.web_search_requests * 0.01
            if web_search_cost > 0:
                cost_usd += web_search_cost
                logger.info(
                    "tools.web_search.user_charged",
                    user_id=user_id,
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
                        model_id=user_model_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        thinking_tokens=usage.thinking_tokens,
                        cache_read_tokens=usage.cache_read_tokens,
                        cache_creation_tokens=usage.cache_creation_tokens,
                        cache_read_cost=round(cache_read_cost, 6),
                        cache_creation_cost=round(cache_creation_cost, 6),
                        cost_usd=round(cost_usd, 6),
                        response_length=len(response_text),
                        stop_reason=stop_reason,
                        claude_api_ms=round(claude_api_ms, 2),
                        total_request_ms=round(total_request_ms, 2))

            # Record Prometheus metrics
            record_claude_request(model=user_model_id, success=True)
            record_claude_tokens(
                model=user_model_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_creation_tokens,
            )
            record_cost(service="claude", amount_usd=cost_usd)
            record_message_sent(chat_type=first_message.chat.type)

            # Record response time for Prometheus
            record_claude_response_time(model=user_model_id,
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
                        # Cosmetic - user already sees the response
                        logger.debug("claude_handler.warning_edit_failed",
                                     error=str(e))

            elif stop_reason == "refusal":
                # External API decision - gracefully handled
                logger.info("claude_handler.refusal", thread_id=thread_id)

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
                        # Cosmetic - user already sees the response
                        logger.debug("claude_handler.refusal_edit_failed",
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
                "model_id": user_model_id,
            }

            queued = await queue_write(WriteType.MESSAGE, message_data)
            if not queued:
                # Fallback to direct DB write if Redis unavailable (graceful degradation)
                logger.info("claude_handler.write_behind_fallback",
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
                    model_id=user_model_id,
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
                "user_id": user_id,
                "messages": len(messages),
                "tokens": total_tokens,
            }
            stats_queued = await queue_write(WriteType.USER_STATS, stats_data)
            if not stats_queued:
                # Fallback to direct DB write
                await services.users.increment_stats(
                    telegram_id=user_id,
                    messages=len(messages),
                    tokens=total_tokens,
                )

            # 12. Update message cache with assistant response (Phase 3.3)
            # Add to cache instead of invalidating (preserves cached history)
            assistant_cache_msg = {
                "role": MessageRole.ASSISTANT.value,
                "text_content": response_text,
                "message_id": bot_message.message_id,
                "date": int(bot_message.date.timestamp()),
            }
            cache_updated = await update_cached_messages(
                thread_id, assistant_cache_msg)
            if not cache_updated:
                # Cache miss (not populated) - invalidate to be safe
                await invalidate_messages(thread_id)

            # Commit any pending direct writes (fallback path)
            await session.commit()

            # Phase 2.1: Charge user for API usage
            try:
                # Build description with all cost components
                desc_parts = [
                    f"Claude API: {usage.input_tokens} in",
                    f"{usage.output_tokens} out",
                ]
                if usage.thinking_tokens:
                    desc_parts.append(f"{usage.thinking_tokens} think")
                if usage.cache_creation_tokens:
                    desc_parts.append(f"{usage.cache_creation_tokens} cache_w")
                if usage.cache_read_tokens:
                    desc_parts.append(f"{usage.cache_read_tokens} cache_r")
                desc_parts.append(f"({model_config.alias})")

                # Charge user for actual cost
                balance_after = await services.balance.charge_user(
                    user_id=user_id,
                    amount=cost_usd,
                    description=" + ".join(desc_parts),
                    related_message_id=bot_message.message_id,
                )

                logger.info(
                    "claude_handler.user_charged",
                    user_id=user_id,
                    model_id=user_model_id,
                    cost_usd=round(cost_usd, 6),
                    balance_after=float(balance_after),
                    thread_id=thread_id,
                    message_id=bot_message.message_id,
                )

                # Update cached balance (Phase 3.3: Cache-First)
                await update_cached_balance(user_id, balance_after)

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "claude_handler.charge_user_error",
                    user_id=user_id,
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

            # Bot API 9.3: Generate topic name after first response
            # Awaited (not fire-and-forget) to ensure session is available
            # Naming is fast (~200ms with Haiku), response already sent to user
            if thread.needs_topic_naming:
                # Extract first user message text for naming context
                first_user_text = ""
                for msg in messages:
                    if msg.text:
                        first_user_text = msg.text
                        break
                    if msg.transcript:
                        first_user_text = msg.transcript.text
                        break

                if first_user_text:
                    # Import here to avoid circular imports
                    from services.topic_naming import \
                        get_topic_naming_service  # pylint: disable=import-outside-toplevel

                    topic_naming = get_topic_naming_service()
                    try:
                        await topic_naming.maybe_name_topic(
                            bot=first_message.bot,
                            thread=thread,
                            user_message=first_user_text,
                            bot_response=response_text,
                            session=session,
                        )
                    except Exception as naming_error:  # pylint: disable=broad-exception-caught
                        # External error, not critical - gracefully handled
                        logger.info(
                            "claude_handler.topic_naming_failed",
                            thread_id=thread_id,
                            error=str(naming_error),
                        )

                    # Persist thread.title and thread.needs_topic_naming changes
                    await session.flush()

    except ContextWindowExceededError as e:
        # External API limit - gracefully handled with user message
        logger.info("claude_handler.context_exceeded",
                    thread_id=thread_id,
                    tokens_used=e.tokens_used,
                    tokens_limit=e.tokens_limit)
        record_error(error_type="context_exceeded", handler="claude")

        await first_message.answer(
            f"⚠️ Context window exceeded.\n\n"
            f"Your conversation is too long ({e.tokens_used:,} tokens). "
            f"Please start a new thread or reduce message history.")

    except RateLimitError as e:
        # External API limit - gracefully handled with user message
        logger.info("claude_handler.rate_limit",
                    thread_id=thread_id,
                    error=str(e),
                    retry_after=e.retry_after)
        record_error(error_type="rate_limit", handler="claude")
        record_claude_request(model="unknown", success=False)

        retry_msg = ""
        if e.retry_after:
            retry_msg = f"\n\nPlease try again in {e.retry_after} seconds."

        await first_message.answer(
            f"⚠️ Rate limit exceeded.{retry_msg}\n\n"
            f"Too many requests. Please wait a moment and try again.")

    except APIConnectionError as e:
        # External infrastructure error - gracefully handled
        logger.info("claude_handler.connection_error",
                    thread_id=thread_id,
                    error=str(e))
        record_error(error_type="connection_error", handler="claude")
        record_claude_request(model="unknown", success=False)

        await first_message.answer(
            "⚠️ Connection error.\n\n"
            "Failed to connect to Claude API. Please check your internet "
            "connection and try again.")

    except APITimeoutError as e:
        # External API timeout - gracefully handled
        logger.info("claude_handler.timeout", thread_id=thread_id, error=str(e))
        record_error(error_type="timeout", handler="claude")
        record_claude_request(model="unknown", success=False)

        await first_message.answer(
            "⚠️ Request timed out.\n\n"
            "The request took too long. Please try again with a shorter "
            "message or simpler question.")

    except LLMError as e:
        # External API error - gracefully handled
        logger.info("claude_handler.llm_error",
                    thread_id=thread_id,
                    error=str(e),
                    error_type=type(e).__name__)
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
