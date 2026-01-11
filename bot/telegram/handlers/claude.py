"""Claude conversation handler.

This module handles all text messages from users, sends them to Claude API,
and streams responses back to Telegram in real-time.

# pylint: disable=too-many-lines

NO __init__.py - use direct import: from telegram.handlers.claude import router
"""

import html as html_lib
import time
from typing import Optional, TYPE_CHECKING

from aiogram import F
from aiogram import Router
from aiogram import types

if TYPE_CHECKING:
    from telegram.media_processor import MediaContent

import config
from config import CLAUDE_TOKEN_BUFFER_PERCENT
from config import get_model
from config import GLOBAL_SYSTEM_PROMPT
from core.claude.client import ClaudeProvider
from core.claude.context import ContextManager
from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import ContextWindowExceededError
from core.exceptions import LLMError
from core.exceptions import RateLimitError
from core.message_queue import MessageQueueManager
from core.models import LLMRequest
from core.models import Message
from core.tools.helpers import extract_tool_uses
from core.tools.helpers import format_files_section
from core.tools.helpers import format_tool_results
from core.tools.helpers import get_available_files
from core.tools.registry import execute_tool
from core.tools.registry import TOOL_DEFINITIONS
from db.engine import get_session
from db.models.message import MessageRole
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_file_repository import UserFileRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.handlers.files import process_file_upload
from utils.structured_logging import get_logger
from utils.metrics import (
    record_message_received,
    record_message_sent,
    record_claude_request,
    record_claude_tokens,
    record_claude_response_time,
    record_tool_call,
    record_cost,
    record_error,
    record_cache_hit,
    record_cache_miss,
    record_messages_batched,
)

logger = get_logger(__name__)

# Create router with name
router = Router(name="claude")


def safe_html(text: str) -> str:
    """Escape HTML special characters for Telegram parse_mode=HTML.

    Prevents "can't parse entities" errors when Claude response contains
    <, >, & symbols (e.g., in code, math, comparisons).

    Args:
        text: Raw text from Claude.

    Returns:
        HTML-escaped text safe for Telegram.
    """
    return html_lib.escape(text)


# Global Claude provider instance (initialized in main.py)
claude_provider: ClaudeProvider = None

# Global message queue manager (initialized in main.py)
# Phase 1.4.3: Per-thread message batching
message_queue_manager: MessageQueueManager = None


def compose_system_prompt(global_prompt: str, custom_prompt: str | None,
                          files_context: str | None) -> str:
    """Compose system prompt from 3 levels.

    Phase 1.4.2 architecture:
    - GLOBAL_SYSTEM_PROMPT (always cached) - base instructions
    - User.custom_prompt (cached) - personal preferences
    - Thread.files_context (NOT cached) - available files list

    Args:
        global_prompt: Base system prompt (same for all users).
        custom_prompt: User's personal instructions (or None).
        files_context: List of files in thread (or None).

    Returns:
        Composed system prompt with all parts joined by double newlines.
    """
    parts = [global_prompt]

    if custom_prompt:
        parts.append(custom_prompt)

    if files_context:
        parts.append(files_context)

    return "\n\n".join(parts)


def init_claude_provider(api_key: str) -> None:
    """Initialize global Claude provider.

    Must be called once during application startup.

    Args:
        api_key: Claude API key from secrets.
    """
    global claude_provider  # pylint: disable=global-statement
    claude_provider = ClaudeProvider(api_key=api_key)
    logger.info("claude_handler.provider_initialized")


def init_message_queue_manager() -> None:
    """Initialize global message queue manager.

    Must be called once during application startup, after init_claude_provider.

    Phase 1.4.3: Per-thread message batching with smart accumulation.
    """
    global message_queue_manager  # pylint: disable=global-statement

    # Create queue manager with processing callback
    message_queue_manager = MessageQueueManager(
        process_callback=_process_message_batch)

    logger.info("claude_handler.message_queue_initialized")


def get_queue_manager() -> MessageQueueManager | None:
    """Get the global message queue manager.

    Returns:
        MessageQueueManager instance or None if not initialized.
    """
    return message_queue_manager


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# pylint: disable=too-many-nested-blocks,unused-argument
async def _handle_with_tools(request: LLMRequest, first_message: types.Message,
                             thread_id: int, session: AsyncSession,
                             user_file_repo: UserFileRepository, chat_id: int,
                             user_id: int,
                             telegram_thread_id: int | None) -> str:
    """Handle request with tool use loop.

    Implements tool use pattern:
    1. Call Claude API (non-streaming)
    2. Check stop_reason
    3. If tool_use: execute tools, add results, repeat
    4. If end_turn: return final text

    Phase 1.5 Stage 6: Processes generated files from execute_python tool,
    uploads to Files API, saves to DB, sends to user via Telegram.

    Args:
        request: LLMRequest with tools configured.
        first_message: First Telegram message (for status updates).
        thread_id: Thread ID for logging.
        session: Database session (for saving generated files).
        user_file_repo: UserFileRepository (for saving file metadata).
        chat_id: Telegram chat ID (for sending files).
        user_id: User ID (for file ownership).
        telegram_thread_id: Telegram thread/topic ID (None for main chat).

    Returns:
        Final text response from Claude (ready for streaming).

    Raises:
        LLMError: If tool loop exceeds max iterations or API errors.
    """
    max_iterations = 10
    status_message = None

    # Build conversation history for tool loop
    # Convert Message objects to dict format for API
    conversation = [{
        "role": msg.role,
        "content": msg.content
    } for msg in request.messages]

    logger.info("tools.loop.start",
                thread_id=thread_id,
                max_iterations=max_iterations,
                has_tools=request.tools is not None)

    for iteration in range(max_iterations):
        logger.info("tools.loop.iteration",
                    thread_id=thread_id,
                    iteration=iteration + 1)

        # Create request for this iteration
        # Use 20K max_tokens for non-streaming (balance between completeness and SDK timeout)
        iter_request = LLMRequest(messages=[
            Message(role=msg["role"], content=msg["content"])
            for msg in conversation
        ],
                                  system_prompt=request.system_prompt,
                                  model=request.model,
                                  max_tokens=min(20480, request.max_tokens),
                                  temperature=request.temperature,
                                  tools=request.tools)

        # Call Claude API (non-streaming)
        try:
            response = await claude_provider.get_message(iter_request)
        except Exception as e:
            logger.error("tools.loop.api_error",
                         thread_id=thread_id,
                         iteration=iteration + 1,
                         error=str(e),
                         exc_info=True)
            raise

        # Check stop reason
        stop_reason = response.stop_reason

        logger.info("tools.loop.response",
                    thread_id=thread_id,
                    iteration=iteration + 1,
                    stop_reason=stop_reason,
                    content_blocks=len(response.content))

        if stop_reason == "end_turn":
            # Final answer - extract text
            final_text = ""
            for block in response.content:
                if block.type == "text":
                    final_text += block.text

            logger.info("tools.loop.complete",
                        thread_id=thread_id,
                        total_iterations=iteration + 1,
                        final_length=len(final_text))

            return final_text

        if stop_reason == "tool_use":
            # Extract tool calls
            tool_uses = extract_tool_uses(response.content)

            if not tool_uses:
                logger.error("tools.loop.no_tools_found",
                             thread_id=thread_id,
                             iteration=iteration + 1)
                return ("⚠️ Internal error: Claude requested tool use but "
                        "no tools found in response.")

            logger.info("tools.loop.executing_tools",
                        thread_id=thread_id,
                        iteration=iteration + 1,
                        tool_count=len(tool_uses))

            # Execute each tool
            results = []
            for idx, tool_use in enumerate(tool_uses):
                tool_name = tool_use["name"]
                tool_input = tool_use["input"]

                # Update user with status
                status_text = f"🔧 {tool_name}..."
                if status_message:
                    try:
                        status_message = await status_message.edit_text(
                            status_text)
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
                else:
                    status_message = await first_message.answer(status_text)

                logger.info("tools.loop.executing_tool",
                            thread_id=thread_id,
                            iteration=iteration + 1,
                            tool_index=idx + 1,
                            tool_name=tool_name)

                # Execute tool with timing
                tool_start_time = time.time()
                try:
                    result = await execute_tool(tool_name, tool_input,
                                                first_message.bot, session)
                    tool_duration = time.time() - tool_start_time

                    # Phase 1.5 Stage 6: Process generated files (if any)
                    if "_file_contents" in result:
                        file_contents = result.pop("_file_contents")

                        logger.info("tools.loop.processing_generated_files",
                                    thread_id=thread_id,
                                    tool_name=tool_name,
                                    file_count=len(file_contents))

                        delivered_files = []

                        for file_data in file_contents:
                            try:
                                filename = file_data["filename"]
                                file_bytes = file_data["content"]
                                mime_type = file_data["mime_type"]

                                logger.info(
                                    "tools.loop.uploading_generated_file",
                                    filename=filename,
                                    size=len(file_bytes),
                                    mime_type=mime_type)

                                # 1. Upload to Files API
                                from core.claude.files_api import \
                                    upload_to_files_api  # pylint: disable=import-outside-toplevel
                                claude_file_id = await upload_to_files_api(
                                    file_bytes=file_bytes,
                                    filename=filename,
                                    mime_type=mime_type)

                                # 2. Save to database (source=ASSISTANT)
                                # pylint: disable=import-outside-toplevel
                                from datetime import datetime
                                from datetime import timedelta
                                from datetime import timezone

                                from config import FILES_API_TTL_HOURS
                                from db.models.user_file import FileSource
                                from db.models.user_file import FileType

                                # Determine file type
                                if mime_type.startswith("image/"):
                                    file_type = FileType.IMAGE
                                elif mime_type == "application/pdf":
                                    file_type = FileType.PDF
                                else:
                                    file_type = FileType.DOCUMENT

                                await user_file_repo.create(
                                    message_id=first_message.message_id,
                                    telegram_file_id=
                                    None,  # No Telegram file ID for generated files
                                    telegram_file_unique_id=None,
                                    claude_file_id=claude_file_id,
                                    filename=filename,
                                    file_type=file_type,
                                    mime_type=mime_type,
                                    file_size=len(file_bytes),
                                    source=FileSource.ASSISTANT,
                                    expires_at=datetime.now(timezone.utc) +
                                    timedelta(hours=FILES_API_TTL_HOURS),
                                    file_metadata={},
                                )

                                # 3. Send to Telegram user
                                # Send as photo if image, otherwise as document
                                # IMPORTANT: Include message_thread_id for forum topics
                                if file_type == FileType.IMAGE and mime_type in [
                                        "image/jpeg", "image/png", "image/gif",
                                        "image/webp"
                                ]:
                                    await first_message.bot.send_photo(
                                        chat_id=chat_id,
                                        photo=types.BufferedInputFile(
                                            file_bytes, filename=filename),
                                        message_thread_id=telegram_thread_id)
                                else:
                                    await first_message.bot.send_document(
                                        chat_id=chat_id,
                                        document=types.BufferedInputFile(
                                            file_bytes, filename=filename),
                                        message_thread_id=telegram_thread_id)

                                delivered_files.append(filename)

                                logger.info(
                                    "tools.loop.generated_file_delivered",
                                    filename=filename,
                                    claude_file_id=claude_file_id,
                                    file_type=file_type.value)

                            except Exception as file_error:  # pylint: disable=broad-exception-caught
                                logger.error(
                                    "tools.loop.failed_to_deliver_file",
                                    filename=filename,
                                    error=str(file_error),
                                    exc_info=True)

                        # Add delivery confirmation to tool result
                        if delivered_files:
                            result["files_delivered"] = (
                                f"Successfully sent {len(delivered_files)} "
                                f"file(s) to user: {', '.join(delivered_files)}"
                            )

                    results.append(result)

                    # Phase 2.1: Charge user for tool execution cost
                    if "cost_usd" in result:
                        try:
                            from decimal import \
                                Decimal  # pylint: disable=import-outside-toplevel

                            from db.repositories.balance_operation_repository import \
                                BalanceOperationRepository  # pylint: disable=import-outside-toplevel
                            from db.repositories.user_repository import \
                                UserRepository  # pylint: disable=import-outside-toplevel
                            from services.balance_service import \
                                BalanceService  # pylint: disable=import-outside-toplevel

                            tool_cost_usd = Decimal(result["cost_usd"])

                            user_repo = UserRepository(session)
                            balance_op_repo = BalanceOperationRepository(
                                session)
                            balance_service = BalanceService(
                                session, user_repo, balance_op_repo)

                            await balance_service.charge_user(
                                user_id=user_id,
                                amount=tool_cost_usd,
                                description=(f"Tool execution: {tool_name}, "
                                             f"cost ${result['cost_usd']}"),
                                related_message_id=first_message.message_id,
                            )

                            await session.commit()

                            logger.info("tools.loop.user_charged_for_tool",
                                        user_id=user_id,
                                        tool_name=tool_name,
                                        cost_usd=float(tool_cost_usd))

                        except Exception as charge_error:  # pylint: disable=broad-exception-caught
                            logger.error(
                                "tools.loop.charge_user_for_tool_error",
                                user_id=user_id,
                                tool_name=tool_name,
                                cost_usd=result.get("cost_usd"),
                                error=str(charge_error),
                                exc_info=True,
                                msg=
                                "CRITICAL: Failed to charge user for tool usage!"
                            )
                            # Don't fail the request - user already got result

                    logger.info("tools.loop.tool_success",
                                thread_id=thread_id,
                                tool_name=tool_name,
                                result_keys=list(result.keys()))

                    # Record tool metrics
                    record_tool_call(tool_name=tool_name, success=True,
                                     duration=tool_duration)
                    if "cost_usd" in result:
                        record_cost(service=tool_name,
                                    amount_usd=float(result["cost_usd"]))

                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Tool execution failed - return error in tool_result
                    tool_duration = time.time() - tool_start_time
                    error_msg = f"Tool execution failed: {str(e)}"
                    results.append({"error": error_msg})

                    logger.error("tools.loop.tool_failed",
                                 thread_id=thread_id,
                                 tool_name=tool_name,
                                 error=str(e),
                                 exc_info=True)

                    # Record failed tool metrics
                    record_tool_call(tool_name=tool_name, success=False,
                                     duration=tool_duration)
                    record_error(error_type="tool_execution", handler=tool_name)

            # Format tool results for API
            tool_results = format_tool_results(tool_uses, results)

            # Add assistant response + tool results to conversation
            # CRITICAL: Include ALL content blocks (thinking + tool_use)
            # Convert ContentBlock objects to dicts for API serialization
            serialized_content = []
            for block in response.content:
                if hasattr(block, 'model_dump'):
                    serialized_content.append(block.model_dump())
                elif hasattr(block, 'dict'):
                    serialized_content.append(block.dict())
                else:
                    serialized_content.append(block)

            conversation.append({
                "role": "assistant",
                "content": serialized_content
            })
            conversation.append({"role": "user", "content": tool_results})

            logger.info("tools.loop.tool_results_added",
                        thread_id=thread_id,
                        iteration=iteration + 1,
                        result_count=len(tool_results))

        else:
            # Other stop reasons (max_tokens, refusal, etc.)
            logger.warning("tools.loop.unexpected_stop_reason",
                           thread_id=thread_id,
                           iteration=iteration + 1,
                           stop_reason=stop_reason)

            # Extract text anyway
            final_text = ""
            for block in response.content:
                if block.type == "text":
                    final_text += block.text

            return final_text or f"⚠️ Unexpected stop reason: {stop_reason}"

    # Max iterations reached
    logger.error("tools.loop.max_iterations",
                 thread_id=thread_id,
                 max_iterations=max_iterations)

    return (
        f"⚠️ Tool loop exceeded maximum iterations ({max_iterations}). "
        "The task might be too complex or there's an issue with tool execution."
    )


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
async def _process_message_batch(
        thread_id: int,
        messages: list[tuple[types.Message, Optional['MediaContent']]]) -> None:
    """Process batch of messages for a thread.

    This function is called by MessageQueueManager when it's time to process
    accumulated messages. Creates its own database session and handles the
    complete flow from saving messages to streaming Claude response.

    Phase 1.4.3: Batch processing with smart accumulation.
    Phase 1.6: Universal media architecture with MediaContent.

    Args:
        thread_id: Database thread ID.
        messages: List of (Message, Optional[MediaContent]) tuples.
    """
    if not messages:
        logger.warning("claude_handler.empty_batch", thread_id=thread_id)
        return

    if claude_provider is None:
        logger.error("claude_handler.provider_not_initialized")
        # Send error to first message
        await messages[0][0].answer(
            "Bot is not properly configured. Please contact administrator.")
        return

    # Use first message for bot/chat context
    first_message = messages[0][0]

    # Calculate content lengths for logging
    content_lengths = []
    for msg, media in messages:
        if media and media.text_content:
            content_lengths.append(len(media.text_content))
        elif msg.text:
            content_lengths.append(len(msg.text))
        else:
            content_lengths.append(0)

    logger.info("claude_handler.batch_received",
                thread_id=thread_id,
                batch_size=len(messages),
                content_lengths=content_lengths,
                has_media=[m is not None for _, m in messages],
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
            for message, media_content in messages:
                # Phase 1.6: Universal media architecture
                # Determine text_content based on media type
                if media_content and media_content.text_content:
                    # Voice/Audio/Video: use transcript with prefix
                    media_type = media_content.type.value
                    duration = media_content.metadata.get("duration", 0)
                    text_content = (
                        f"[{media_type.upper()} MESSAGE - {duration}s]: "
                        f"{media_content.text_content}")
                elif media_content and media_content.file_id:
                    # Image/PDF/Document: use caption or file mention
                    if message.caption:
                        text_content = message.caption
                    else:
                        # Generate file mention
                        media_type = media_content.type.value
                        filename = media_content.metadata.get(
                            "filename", "file")
                        size = media_content.metadata.get("size_bytes", 0)
                        text_content = (
                            f"📎 User uploaded {media_type}: {filename} "
                            f"({size} bytes) [file_id: {media_content.file_id}]"
                        )
                else:
                    # Regular text message or captioned media
                    text_content = message.text or message.caption

                await msg_repo.create_message(
                    chat_id=thread.chat_id,
                    message_id=message.message_id,
                    thread_id=thread_id,
                    from_user_id=thread.user_id,
                    date=message.date.timestamp(),
                    role=MessageRole.USER,
                    text_content=text_content,
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
            logger.debug("claude_handler.creating_file_repo",
                         thread_id=thread_id)
            user_file_repo = UserFileRepository(session)
            logger.debug("claude_handler.calling_get_available_files",
                         thread_id=thread_id,
                         repo_type=type(user_file_repo).__name__)
            available_files = await get_available_files(thread_id,
                                                        user_file_repo)

            logger.info("claude_handler.files_retrieved",
                        thread_id=thread_id,
                        file_count=len(available_files))

            # 4. Get thread history (includes newly saved messages)
            history = await msg_repo.get_thread_messages(thread_id)

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

            # Phase 1.5: Generate files section for system prompt
            files_section = format_files_section(
                available_files) if available_files else None

            # Phase 1.4.2: Compose 3-level system prompt (+ Phase 1.5 files)
            composed_prompt = compose_system_prompt(
                global_prompt=GLOBAL_SYSTEM_PROMPT,
                custom_prompt=user.custom_prompt,
                files_context=files_section)

            logger.info("claude_handler.system_prompt_composed",
                        thread_id=thread_id,
                        telegram_thread_id=thread.thread_id,
                        has_custom_prompt=user.custom_prompt is not None,
                        has_files_context=files_section is not None,
                        total_length=len(composed_prompt))

            # Convert DB messages to LLM messages
            llm_messages = [
                Message(role="user" if msg.from_user_id else "assistant",
                        content=msg.text_content) for msg in history
            ]

            context = await context_mgr.build_context(
                messages=llm_messages,
                model_context_window=model_config.context_window,
                system_prompt=composed_prompt,
                max_output_tokens=model_config.max_output,
                buffer_percent=CLAUDE_TOKEN_BUFFER_PERCENT)

            logger.info("claude_handler.context_built",
                        thread_id=thread_id,
                        included_messages=len(context),
                        total_messages=len(llm_messages))

            # 6. Prepare Claude request (Phase 1.5: tools always available)
            # Server-side tools (web_search, web_fetch) work without files
            # Client-side tools (analyze_image, analyze_pdf) require uploaded files
            request = LLMRequest(messages=context,
                                 system_prompt=composed_prompt,
                                 model=user.model_id,
                                 max_tokens=model_config.max_output,
                                 temperature=config.CLAUDE_TEMPERATURE,
                                 tools=TOOL_DEFINITIONS)  # Always pass tools

            logger.info("claude_handler.request_prepared",
                        thread_id=thread_id,
                        has_tools=request.tools is not None,
                        tool_count=len(request.tools) if request.tools else 0)

            # 7. Show typing indicator (only when starting processing)
            await first_message.bot.send_chat_action(first_message.chat.id,
                                                     "typing")

            # Start timing for response metrics
            request_start_time = time.perf_counter()

            # 8. Handle request (Phase 1.5: always with tools)
            # Tools are always passed for:
            # - Prompt caching stability (tools = part of cached prompt)
            # - Model awareness (can suggest tools proactively)
            # - Server-side tools work without files (web_search, web_fetch)
            if request.tools:
                # Tool loop (non-streaming until final answer)
                logger.info("claude_handler.using_tools",
                            thread_id=thread_id,
                            tool_count=len(request.tools))

                try:
                    response_text = await _handle_with_tools(
                        request, first_message, thread_id, session,
                        user_file_repo, thread.chat_id, thread.user_id,
                        thread.thread_id)

                    # Send final response (no streaming, already processed)
                    # Escape HTML to prevent Telegram parse errors with <, >, & symbols
                    # IMPORTANT: Escape BEFORE length check (escape increases length)
                    safe_text = html_lib.escape(response_text)

                    # Split if too long (Telegram limit: 4096 chars)
                    if len(safe_text) > 4000:
                        # Send in chunks
                        for i in range(0, len(safe_text), 4000):
                            chunk = safe_text[i:i + 4000]
                            bot_message = await first_message.answer(chunk)
                    else:
                        bot_message = await first_message.answer(safe_text)

                    logger.info("claude_handler.tool_response_sent",
                                thread_id=thread_id,
                                response_length=len(response_text))

                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("claude_handler.tool_loop_failed",
                                 thread_id=thread_id,
                                 error=str(e),
                                 exc_info=True)
                    bot_message = await first_message.answer(
                        "⚠️ Tool execution failed. Please try again.")
                    return

            else:
                # Direct streaming (no tools)
                logger.info("claude_handler.streaming_response",
                            thread_id=thread_id)

                response_text = ""
                last_sent_text = ""
                bot_message = None
                last_edit_time = 0.0
                edit_buffer_ms = 0.5

                async for chunk in claude_provider.stream_message(request):
                    response_text += chunk
                    current_time = time.time()

                    time_since_last_edit = current_time - last_edit_time
                    should_update = (time_since_last_edit >= edit_buffer_ms or
                                     bot_message is None)

                    # Check if message needs to be split (use smaller limit due to escape)
                    # Escape can increase length up to 5x for special chars
                    if len(response_text) > 3500:
                        text_to_send = response_text[:3500]
                        safe_text = safe_html(text_to_send)

                        if bot_message is None:
                            bot_message = await first_message.answer(safe_text)
                            last_sent_text = text_to_send
                            last_edit_time = current_time
                        elif text_to_send != last_sent_text:
                            try:
                                await bot_message.edit_text(safe_text)
                                last_sent_text = text_to_send
                                last_edit_time = current_time
                            except Exception as e:  # pylint: disable=broad-exception-caught
                                logger.warning("claude_handler.edit_failed",
                                               error=str(e))

                        # Start new message with remaining text
                        response_text = response_text[3500:]
                        bot_message = None
                        last_sent_text = ""
                        last_edit_time = 0.0
                    elif should_update:
                        safe_text = safe_html(response_text)
                        if bot_message is None:
                            bot_message = await first_message.answer(safe_text)
                            last_sent_text = response_text
                            last_edit_time = current_time
                        elif response_text != last_sent_text:
                            try:
                                await bot_message.edit_text(safe_text)
                                last_sent_text = response_text
                                last_edit_time = current_time
                            except Exception as e:  # pylint: disable=broad-exception-caught
                                logger.warning("claude_handler.edit_failed",
                                               error=str(e))

                # Final update if there's remaining text
                if response_text:
                    safe_text = safe_html(response_text)
                    if bot_message is None:
                        bot_message = await first_message.answer(safe_text)
                    elif response_text != last_sent_text:
                        try:
                            await bot_message.edit_text(safe_text)
                        except Exception as e:  # pylint: disable=broad-exception-caught
                            logger.warning("claude_handler.final_edit_failed",
                                           error=str(e))
                            # Try sending as plain text (no HTML parsing)
                            try:
                                bot_message = await first_message.answer(
                                    response_text, parse_mode=None)
                                logger.info("claude_handler.sent_as_plain_text",
                                            thread_id=thread_id)
                            except Exception as plain_error:  # pylint: disable=broad-exception-caught
                                logger.error("claude_handler.plain_text_failed",
                                             thread_id=thread_id,
                                             error=str(plain_error),
                                             exc_info=True)
                                raise
                else:
                    # Handle empty response from Claude
                    logger.warning("claude_handler.empty_response",
                                   thread_id=thread_id,
                                   batch_size=len(messages))
                    bot_message = await first_message.answer(
                        "⚠️ Claude returned an empty response. "
                        "Please try rephrasing your message.")

            # Check bot_message exists (for both tools and streaming paths)
            if not bot_message:
                logger.error("claude_handler.no_bot_message",
                             thread_id=thread_id)
                await first_message.answer("Failed to send response.")
                return

            # 9. Get usage stats, stop_reason, thinking, and calculate cost
            usage = await claude_provider.get_usage()
            stop_reason = claude_provider.get_stop_reason()
            thinking = claude_provider.get_thinking(
            )  # Phase 1.4.3: Extended Thinking

            cost_usd = (
                (usage.input_tokens / 1_000_000) * model_config.pricing_input +
                ((usage.output_tokens + usage.thinking_tokens) / 1_000_000) *
                model_config.pricing_output)

            logger.info("claude_handler.response_complete",
                        thread_id=thread_id,
                        model_id=user.model_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        thinking_tokens=usage.thinking_tokens,
                        cost_usd=round(cost_usd, 6),
                        response_length=len(response_text),
                        stop_reason=stop_reason)

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

            # Record response time
            response_duration = time.perf_counter() - request_start_time
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

            # 10. Save Claude response (Phase 1.4.3: with thinking blocks)
            await msg_repo.create_message(
                chat_id=thread.chat_id,
                message_id=bot_message.message_id,
                thread_id=thread_id,
                from_user_id=None,  # Bot message
                date=bot_message.date.timestamp(),
                role=MessageRole.ASSISTANT,
                text_content=response_text,
                thinking_blocks=thinking,  # Phase 1.4.3: Extended Thinking
            )

            # 11. Add token usage for billing (Phase 1.4.2 & 1.4.3)
            await msg_repo.add_tokens(
                chat_id=thread.chat_id,
                message_id=bot_message.message_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                thinking_tokens=usage.thinking_tokens,
            )

            # 12. Update user statistics (Phase 3: metrics)
            total_tokens = usage.input_tokens + usage.output_tokens
            if usage.thinking_tokens:
                total_tokens += usage.thinking_tokens
            await user_repo.increment_stats(
                telegram_id=user.id,
                messages=len(messages),
                tokens=total_tokens,
            )

            await session.commit()

            # Phase 2.1: Charge user for API usage
            try:
                from db.repositories.balance_operation_repository import \
                    BalanceOperationRepository
                from services.balance_service import BalanceService

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


@router.message(F.text | (F.photo & F.caption) | (F.document & F.caption))
async def handle_claude_message(message: types.Message,
                                session: AsyncSession) -> None:
    """Handle text message or file with caption.

    Phase 1.5: Support for photos/documents with caption.
    Phase 1.4.3: Per-thread message batching with smart accumulation.

    Flow:
    1. If photo/document with caption → upload to Files API first
    2. Get or create user, chat, thread
    3. Add message to thread's queue
    4. Queue manager decides when to process (immediately or after 300ms)

    Args:
        message: Incoming Telegram message (text or file with caption).
        session: Database session (injected by middleware).
    """
    if message_queue_manager is None:
        logger.error("claude_handler.queue_not_initialized")
        await message.answer(
            "Bot is not properly configured. Please contact administrator.")
        return

    # Phase 1.5: If photo/document with caption, upload file first
    if message.photo or message.document:
        logger.info("claude_handler.file_with_caption_received",
                    chat_id=message.chat.id,
                    user_id=message.from_user.id if message.from_user else None,
                    has_photo=bool(message.photo),
                    has_document=bool(message.document),
                    caption_length=len(message.caption or ""))

        try:
            # Upload file to Files API and save to database
            await process_file_upload(message, session)
            # Continue processing caption as text below
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("claude_handler.file_upload_failed",
                         error=str(e),
                         exc_info=True)
            await message.answer("❌ Failed to upload file. Please try again.")
            return

    logger.info("claude_handler.message_received",
                chat_id=message.chat.id,
                user_id=message.from_user.id if message.from_user else None,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                is_topic_message=message.is_topic_message,
                text_length=len(message.text or message.caption or ""))

    # Record metrics
    content_type = "text"
    if message.photo:
        content_type = "photo"
    elif message.document:
        content_type = "document"
    record_message_received(chat_type=message.chat.type, content_type=content_type)

    try:
        # 1. Get or create user
        user_repo = UserRepository(session)
        if not message.from_user:
            logger.warning("claude_handler.no_from_user",
                           chat_id=message.chat.id)
            await message.answer("Cannot process messages without user info.")
            return

        user, was_created = await user_repo.get_or_create(
            telegram_id=message.from_user.id,
            is_bot=message.from_user.is_bot,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code,
            is_premium=message.from_user.is_premium or False,
        )

        if was_created:
            logger.info("claude_handler.user_created",
                        user_id=user.id,
                        telegram_id=user.id)

        # 2. Get or create chat
        chat_repo = ChatRepository(session)
        chat, was_created = await chat_repo.get_or_create(
            telegram_id=message.chat.id,
            chat_type=message.chat.type,
            title=message.chat.title,
            username=message.chat.username,
            first_name=message.chat.first_name,
            last_name=message.chat.last_name,
            is_forum=message.chat.is_forum or False,
        )

        if was_created:
            logger.info("claude_handler.chat_created",
                        chat_id=chat.id,
                        telegram_id=chat.id)

        # 3. Get or create thread (Phase 1.4.3: Telegram Topics support)
        # message.message_thread_id from Bot API 9.3
        # - None for regular chats (one thread per chat)
        # - Integer for forum topics (separate context per topic)
        thread_repo = ThreadRepository(session)

        # Generate thread title from chat/user info
        thread_title = (
            message.chat.title  # Groups/supergroups
            or message.chat.first_name  # Private chats
            or message.from_user.first_name if message.from_user else None
        )

        thread, was_created = await thread_repo.get_or_create_thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=message.message_thread_id,  # Telegram forum thread ID
            title=thread_title,
        )

        if was_created:
            logger.info("claude_handler.thread_created",
                        thread_id=thread.id,
                        telegram_thread_id=message.message_thread_id)

        # CRITICAL: Commit immediately so queue manager can see the thread
        # Phase 1.4.3: Avoid race condition between parallel sessions
        await session.commit()

        # 4. Add message to queue (queue manager handles the rest)
        # Phase 1.4.3: Smart batching
        # - Long messages (>4000 chars) → wait 300ms for split parts
        # - Short messages → process immediately
        # - During processing → accumulate for next batch
        await message_queue_manager.add_message(thread.id, message)

        logger.debug("claude_handler.message_queued",
                     thread_id=thread.id,
                     message_id=message.message_id)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("claude_handler.queue_error",
                     error=str(e),
                     error_type=type(e).__name__,
                     exc_info=True)

        await message.answer("⚠️ Failed to queue message.\n\n"
                             "Please try again or contact administrator.")
