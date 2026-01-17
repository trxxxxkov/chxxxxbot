"""Claude conversation handler.

This module handles all text messages from users, sends them to Claude API,
and streams responses back to Telegram in real-time.

# pylint: disable=too-many-lines

NO __init__.py - use direct import: from telegram.handlers.claude import router
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

from aiogram import F
from aiogram import Router
from aiogram import types
from aiogram.exceptions import TelegramRetryAfter

if TYPE_CHECKING:
    from telegram.media_processor import MediaContent

import config
from config import CLAUDE_TOKEN_BUFFER_PERCENT
from config import FILES_API_TTL_HOURS
from config import get_model
from config import GLOBAL_SYSTEM_PROMPT
from config import MESSAGE_SPLIT_LENGTH
from config import MESSAGE_TRUNCATE_LENGTH
from config import STREAM_UPDATE_INTERVAL
from config import TEXT_SPLIT_LINE_WINDOW
from config import TEXT_SPLIT_PARA_WINDOW
from config import TOOL_LOOP_MAX_ITERATIONS
from core.claude.client import ClaudeProvider
from core.claude.context import ContextManager
from core.claude.files_api import upload_to_files_api
from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import ContextWindowExceededError
from core.exceptions import LLMError
from core.exceptions import RateLimitError
from core.message_queue import MessageQueueManager
from core.models import LLMRequest
from core.models import Message
from core.models import StreamEvent
from core.tools.helpers import extract_tool_uses
from core.tools.helpers import format_files_section
from core.tools.helpers import format_tool_results
from core.tools.helpers import get_available_files
from core.tools.registry import execute_tool
from core.tools.registry import get_tool_definitions
from core.tools.registry import get_tool_emoji
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
from telegram.handlers.files import process_file_upload
from utils.metrics import record_cache_hit
from utils.metrics import record_cache_miss
from utils.metrics import record_claude_request
from utils.metrics import record_claude_response_time
from utils.metrics import record_claude_tokens
from utils.metrics import record_cost
from utils.metrics import record_error
from utils.metrics import record_message_received
from utils.metrics import record_message_sent
from utils.metrics import record_messages_batched
from utils.metrics import record_tool_call
from utils.structured_logging import get_logger

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


def strip_tool_markers(text: str) -> str:
    """Remove tool markers and system messages from final response.

    During streaming, markers like [📄 analyze_pdf] are shown in thinking.
    The final answer should be clean text without these markers.

    Patterns removed:
    - Tool markers: [📄 analyze_pdf], [🐍 execute_python], etc.
    - System messages: [✅ ...], [❌ ...], [🎨 ...], [📤 ...]

    Args:
        text: Response text with possible markers.

    Returns:
        Clean text without tool markers.
    """
    # Pattern matches: newline + [emoji + text] + newline
    # Also handles markers at start/end of text
    # Emojis: 📄 analyze_pdf, 🐍 execute_python, 🎨 generate_image,
    #         🔍 web_search, 🌐 web_fetch, 🖼️ analyze_image, 🎤 transcribe_audio
    #         📤 file sent, ✅/❌ status, 📎 document
    pattern = r'\n?\[(?:📄|🐍|🎨|🔍|📤|✅|❌|🌐|📎|🖼️|🎤)[^\]]*\]\n?'
    cleaned = re.sub(pattern, '\n', text)
    # Clean up multiple newlines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def format_interleaved_content(blocks: list[dict],
                               is_streaming: bool = True) -> str:
    """Format interleaved thinking and text blocks for Telegram display.

    Preserves the original order of blocks as output by Claude.
    During streaming: Show thinking in italics with 🧠 prefix
    Final display: Show thinking in expandable blockquote

    Args:
        blocks: List of {"type": "thinking"|"text", "content": str} dicts.
        is_streaming: Whether we're still streaming (affects formatting).

    Returns:
        Formatted HTML string for Telegram.
    """
    parts = []

    for block in blocks:
        content = block.get("content", "")
        if not content or not content.strip():
            continue

        # Strip whitespace to avoid double newlines between blocks
        escaped = safe_html(content.strip())

        if block.get("type") == "thinking":
            if is_streaming:
                parts.append(f"<i>🧠 {escaped}</i>")
            else:
                parts.append(f"<blockquote expandable>🧠 {escaped}</blockquote>")
        else:  # text block
            parts.append(escaped)

    result = "\n\n".join(parts) if parts else ""
    # Clean up any triple+ newlines that might still occur
    return re.sub(r'\n{3,}', '\n\n', result)


def format_thinking_display(thinking_text: str,
                            response_text: str,
                            is_streaming: bool = True) -> str:
    """Format thinking and response for Telegram display.

    DEPRECATED: Use format_interleaved_content for proper ordering.
    This function assumes thinking always comes before response.

    Args:
        thinking_text: The thinking/reasoning text from Claude.
        response_text: The actual response text.
        is_streaming: Whether we're still streaming (affects formatting).

    Returns:
        Formatted HTML string for Telegram.
    """
    blocks = []
    if thinking_text:
        blocks.append({"type": "thinking", "content": thinking_text})
    if response_text:
        blocks.append({"type": "text", "content": response_text})
    return format_interleaved_content(blocks, is_streaming)


def split_text_smart(text: str,
                     max_length: int = MESSAGE_SPLIT_LENGTH) -> list[str]:
    """Split text into chunks using smart boundaries.

    Uses priority-based splitting:
    1. Paragraph boundaries (double newline) - preserves semantic units
    2. Single newlines - preserves line structure
    3. Hard split at max_length if no better option

    Args:
        text: Text to split.
        max_length: Maximum length per chunk (default: MESSAGE_SPLIT_LENGTH).

    Returns:
        List of text chunks.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_length:
        split_pos = max_length

        # Try paragraph boundary first
        para_pos = remaining.rfind('\n\n', 0, split_pos)
        if para_pos > split_pos - TEXT_SPLIT_PARA_WINDOW and para_pos > 0:
            split_pos = para_pos + 1

        # Fall back to single newline
        elif (newline_pos :=
              remaining.rfind('\n', 0,
                              split_pos)) > split_pos - TEXT_SPLIT_LINE_WINDOW:
            if newline_pos > 0:
                split_pos = newline_pos

        chunks.append(remaining[:split_pos].strip())
        remaining = remaining[split_pos:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


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
# pylint: disable=too-many-nested-blocks
async def _stream_with_unified_events(
    request: LLMRequest,
    first_message: types.Message,
    thread_id: int,
    session: AsyncSession,
    user_file_repo: UserFileRepository,
    chat_id: int,
    user_id: int,
    telegram_thread_id: int | None,
) -> tuple[str, list[types.Message]]:
    """Stream response with unified thinking/text/tool handling.

    Unified streaming approach:
    1. Stream thinking and text together (both visible to user)
    2. On tool_use: append [emoji tool_name], execute, continue
    3. Track all sent messages for cleanup
    4. Return final answer (text after last tool) and messages to delete

    Args:
        request: LLMRequest with tools configured.
        first_message: First Telegram message (for replies).
        thread_id: Thread ID for logging.
        session: Database session.
        user_file_repo: UserFileRepository for file handling.
        chat_id: Telegram chat ID.
        user_id: User ID.
        telegram_thread_id: Telegram thread/topic ID.

    Returns:
        Tuple of (final_answer_text, list_of_messages_to_delete).
    """
    max_iterations = TOOL_LOOP_MAX_ITERATIONS
    all_sent_messages: list[types.Message] = []

    # Build conversation for tool loop
    conversation = [{
        "role": msg.role,
        "content": msg.content
    } for msg in request.messages]

    logger.info("stream.unified.start",
                thread_id=thread_id,
                max_iterations=max_iterations)

    # Streaming state - PERSIST ACROSS ITERATIONS to keep single message
    # Track blocks in order for proper interleaving of thinking and text
    display_blocks: list[dict] = [
    ]  # [{"type": "thinking"|"text", "content": str}]
    current_block_type_global = ""  # Track current block type across stream
    last_sent_text = ""  # Track what we've already sent (formatted)
    current_message: types.Message | None = None
    last_update_time = 0.0

    for iteration in range(max_iterations):
        logger.info("stream.unified.iteration",
                    thread_id=thread_id,
                    iteration=iteration + 1)

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

        # Per-iteration state (reset each iteration)
        pending_tools: list[dict] = []  # Tools to execute after stream ends
        stop_reason = ""
        # Capture final message from stream_complete to avoid race condition
        # (other requests can reset claude_provider.last_message during tool exec)
        captured_final_message = None

        # Collect content blocks directly from stream (avoid race condition)
        content_blocks: list[dict] = []
        current_thinking_text = ""
        current_response_text = ""
        current_block_type = ""  # "thinking" | "text" | ""

        # Helper to append content to display_blocks with proper ordering
        def append_to_display(block_type: str, content: str) -> None:
            """Append content to display_blocks, merging with last block if same type."""
            nonlocal current_block_type_global
            if not display_blocks or display_blocks[-1]["type"] != block_type:
                # Start new block
                display_blocks.append({"type": block_type, "content": content})
                current_block_type_global = block_type
            else:
                # Append to existing block
                display_blocks[-1]["content"] += content

        # Stream events
        async for event in claude_provider.stream_events(iter_request):
            if event.type == "thinking_delta":
                append_to_display("thinking", event.content)
                current_thinking_text += event.content
                current_block_type = "thinking"
                current_time = time.time()

                # Format display text preserving block order
                display_text = format_interleaved_content(display_blocks,
                                                          is_streaming=True)

                # Update Telegram every 400ms if text changed
                if (current_time - last_update_time >= STREAM_UPDATE_INTERVAL
                        and display_text != last_sent_text):
                    current_message, last_sent_text = (
                        await _update_telegram_message_formatted(
                            display_text,
                            current_message,
                            first_message,
                            all_sent_messages,
                            last_sent_text,
                        ))
                    last_update_time = current_time

            elif event.type == "text_delta":
                append_to_display("text", event.content)
                current_response_text += event.content
                current_block_type = "text"
                current_time = time.time()

                # Format display text preserving block order
                display_text = format_interleaved_content(display_blocks,
                                                          is_streaming=True)

                # Update Telegram every 400ms if text changed
                if (current_time - last_update_time >= STREAM_UPDATE_INTERVAL
                        and display_text != last_sent_text):
                    current_message, last_sent_text = (
                        await _update_telegram_message_formatted(
                            display_text,
                            current_message,
                            first_message,
                            all_sent_messages,
                            last_sent_text,
                        ))
                    last_update_time = current_time

            elif event.type == "tool_use":
                # Finalize any pending text block before tool
                if current_block_type == "thinking" and current_thinking_text:
                    content_blocks.append({
                        "type": "thinking",
                        "thinking": current_thinking_text
                    })
                    current_thinking_text = ""
                elif current_block_type == "text" and current_response_text:
                    content_blocks.append({
                        "type": "text",
                        "text": current_response_text
                    })
                    current_response_text = ""
                current_block_type = ""

                # Add tool marker as text block (shown during streaming)
                emoji = get_tool_emoji(event.tool_name)
                tool_marker = f"[{emoji} {event.tool_name}]"
                append_to_display("text", f"\n\n{tool_marker}\n\n")

                # Format and force update to show tool marker
                display_text = format_interleaved_content(display_blocks,
                                                          is_streaming=True)
                current_message, last_sent_text = (
                    await _update_telegram_message_formatted(
                        display_text,
                        current_message,
                        first_message,
                        all_sent_messages,
                        last_sent_text,
                    ))
                last_update_time = time.time()

                logger.info("stream.unified.tool_detected",
                            thread_id=thread_id,
                            tool_name=event.tool_name,
                            tool_id=event.tool_id)

            elif event.type == "block_end":
                # Finalize current block
                if current_block_type == "thinking" and current_thinking_text:
                    content_blocks.append({
                        "type": "thinking",
                        "thinking": current_thinking_text
                    })
                    current_thinking_text = ""
                elif current_block_type == "text" and current_response_text:
                    content_blocks.append({
                        "type": "text",
                        "text": current_response_text
                    })
                    current_response_text = ""
                current_block_type = ""

                # Add tool_use block to content_blocks
                if event.tool_name and event.tool_id:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": event.tool_id,
                        "name": event.tool_name,
                        "input": event.tool_input or {}
                    })

                    # Only client-side tools need execution (have tool_input)
                    if event.tool_input:
                        pending_tools.append({
                            "id": event.tool_id,
                            "name": event.tool_name,
                            "input": event.tool_input,
                        })

            elif event.type == "message_end":
                stop_reason = event.stop_reason
                # Finalize any remaining text block
                if current_thinking_text:
                    content_blocks.append({
                        "type": "thinking",
                        "thinking": current_thinking_text
                    })
                if current_response_text:
                    content_blocks.append({
                        "type": "text",
                        "text": current_response_text
                    })

            elif event.type == "stream_complete":
                # Capture final message immediately to avoid race condition
                # (another request could reset claude_provider state during tools)
                captured_final_message = event.final_message

        # Final update for any remaining text (with formatting)
        display_text = format_interleaved_content(display_blocks,
                                                  is_streaming=True)
        if display_text and display_text != last_sent_text:
            current_message, last_sent_text = (
                await _update_telegram_message_formatted(
                    display_text,
                    current_message,
                    first_message,
                    all_sent_messages,
                    last_sent_text,
                ))

        # Calculate lengths for logging
        total_thinking = sum(
            len(b["content"])
            for b in display_blocks
            if b["type"] == "thinking")
        total_response = sum(
            len(b["content"]) for b in display_blocks if b["type"] == "text")

        logger.info("stream.unified.iteration_complete",
                    thread_id=thread_id,
                    iteration=iteration + 1,
                    stop_reason=stop_reason,
                    pending_tools=len(pending_tools),
                    thinking_length=total_thinking,
                    response_length=total_response)

        if stop_reason in ("end_turn", "pause_turn"):
            # Final answer: join all text blocks (strip tool markers later)
            final_answer = "\n\n".join(b["content"]
                                       for b in display_blocks
                                       if b["type"] == "text").strip()

            logger.info("stream.unified.complete",
                        thread_id=thread_id,
                        total_iterations=iteration + 1,
                        final_answer_length=len(final_answer),
                        messages_to_cleanup=len(all_sent_messages) - 1,
                        stop_reason=stop_reason,
                        had_thinking=total_thinking > 0)

            return final_answer, all_sent_messages

        if stop_reason == "tool_use" and pending_tools:
            # Execute tools and continue
            results = []
            for tool in pending_tools:
                tool_name = tool["name"]
                tool_input = tool["input"]

                logger.info("stream.unified.executing_tool",
                            thread_id=thread_id,
                            tool_name=tool_name)

                tool_start_time = time.time()
                try:
                    result = await execute_tool(tool_name, tool_input,
                                                first_message.bot, session)
                    tool_duration = time.time() - tool_start_time

                    # Add system messages for completed tools FIRST
                    # (e.g., "🎨 Изображение сгенерировано" before "📤 Отправлен")
                    tool_system_msg = get_tool_system_message(
                        tool_name, tool_input, result)
                    if tool_system_msg:
                        append_to_display("text", tool_system_msg)

                    # Process generated files (upload to Files API, send to user)
                    if "_file_contents" in result:
                        file_contents = result["_file_contents"]
                        await _process_generated_files(result, first_message,
                                                       thread_id, session,
                                                       user_file_repo, chat_id,
                                                       user_id,
                                                       telegram_thread_id)
                        # Add system message markers for delivered files
                        for file_info in file_contents:
                            filename = file_info.get("filename", "file")
                            append_to_display(
                                "text", f"\n[📤 Отправлен файл: {filename}]\n")

                    results.append(result)

                    # Charge user for tool cost
                    if "cost_usd" in result:
                        await _charge_for_tool(session, user_id, tool_name,
                                               result, first_message.message_id)

                    logger.info("stream.unified.tool_success",
                                thread_id=thread_id,
                                tool_name=tool_name,
                                duration_ms=round(tool_duration * 1000))

                    record_tool_call(tool_name=tool_name,
                                     success=True,
                                     duration=tool_duration)
                    if "cost_usd" in result:
                        record_cost(service=tool_name,
                                    amount_usd=float(result["cost_usd"]))

                    # Update display immediately after each tool completes
                    # (so user sees progress, not all at once)
                    display_text = format_interleaved_content(display_blocks,
                                                              is_streaming=True)
                    if display_text != last_sent_text:
                        current_message, last_sent_text = (
                            await _update_telegram_message_formatted(
                                display_text,
                                current_message,
                                first_message,
                                all_sent_messages,
                                last_sent_text,
                            ))
                        last_update_time = time.time()

                except Exception as e:  # pylint: disable=broad-exception-caught
                    tool_duration = time.time() - tool_start_time
                    error_msg = f"Tool execution failed: {str(e)}"
                    results.append({"error": error_msg})

                    logger.error("stream.unified.tool_failed",
                                 thread_id=thread_id,
                                 tool_name=tool_name,
                                 error=str(e),
                                 exc_info=True)

                    record_tool_call(tool_name=tool_name,
                                     success=False,
                                     duration=tool_duration)
                    record_error(error_type="tool_execution", handler=tool_name)

            # Format tool results
            tool_uses = [{
                "id": t["id"],
                "name": t["name"]
            } for t in pending_tools]
            tool_results = format_tool_results(tool_uses, results)

            # Add to conversation using captured_final_message (NOT provider state)
            # CRITICAL: Use captured message which has thinking blocks with
            # signatures (required by API). Provider state may be reset by other
            # concurrent requests during tool execution.
            final_message = captured_final_message
            if final_message and final_message.content:
                serialized_content = []
                for block in final_message.content:
                    if hasattr(block, 'model_dump'):
                        serialized_content.append(block.model_dump())
                    else:
                        serialized_content.append(block)
                conversation.append({
                    "role": "assistant",
                    "content": serialized_content
                })
                # Only add tool_results if we have the assistant message
                # (tool_results reference tool_use blocks in assistant message)
                conversation.append({"role": "user", "content": tool_results})
            else:
                # No assistant message - can't continue tool loop safely
                logger.error("stream.unified.no_assistant_message",
                             thread_id=thread_id,
                             tool_count=len(pending_tools))
                return "⚠️ Tool execution error: missing assistant context", all_sent_messages

            # Update message to show system messages after tool execution
            display_text = format_interleaved_content(display_blocks,
                                                      is_streaming=True)
            if display_text != last_sent_text:
                current_message, last_sent_text = (
                    await _update_telegram_message_formatted(
                        display_text,
                        current_message,
                        first_message,
                        all_sent_messages,
                        last_sent_text,
                    ))
                last_update_time = time.time()

            logger.info("stream.unified.tool_results_added",
                        thread_id=thread_id,
                        tool_count=len(pending_tools))

        else:
            # Unexpected stop reason
            logger.warning("stream.unified.unexpected_stop",
                           thread_id=thread_id,
                           stop_reason=stop_reason)

            final_answer = "\n\n".join(b["content"]
                                       for b in display_blocks
                                       if b["type"] == "text").strip()
            if not final_answer:
                final_answer = f"⚠️ Unexpected stop reason: {stop_reason}"

            return final_answer, all_sent_messages

    # Max iterations exceeded
    logger.error("stream.unified.max_iterations",
                 thread_id=thread_id,
                 max_iterations=max_iterations)

    error_msg = (
        f"⚠️ Tool loop exceeded maximum iterations ({max_iterations}). "
        "The task might be too complex.")
    return error_msg, all_sent_messages


async def _update_telegram_message_formatted(
    formatted_html: str,
    current_message: types.Message | None,
    first_message: types.Message,
    all_messages: list[types.Message],
    last_sent_text: str,
) -> tuple[types.Message | None, str]:
    """Update or send Telegram message with pre-formatted HTML.

    Similar to _update_telegram_message but accepts already-formatted HTML
    (e.g., with thinking in expandable blockquote).

    Has robust error handling: if HTML fails, falls back to plain text.

    Args:
        formatted_html: Pre-formatted HTML text ready for Telegram.
        current_message: Current message being edited (or None).
        first_message: Original user message (for reply).
        all_messages: List to track all sent messages.
        last_sent_text: Previously sent text (to avoid duplicate edits).

    Returns:
        Tuple of (current_message, new_last_sent_text).
    """
    # Skip if nothing changed
    if formatted_html == last_sent_text:
        return current_message, last_sent_text

    # For formatted HTML, check length directly
    # (splitting is complex with HTML tags, so just truncate for now)
    safe_text = formatted_html
    if len(safe_text) > MESSAGE_TRUNCATE_LENGTH:
        # Truncate with ellipsis - simple approach for streaming
        safe_text = safe_text[:MESSAGE_TRUNCATE_LENGTH] + "..."

    # Try HTML first, fall back to plain text if it fails
    for parse_mode, text_to_send in [("HTML", safe_text),
                                     (None, _strip_html(safe_text))]:
        try:
            if current_message:
                await current_message.edit_text(text_to_send,
                                                parse_mode=parse_mode)
            else:
                current_message = await first_message.answer(
                    text_to_send, parse_mode=parse_mode)
                all_messages.append(current_message)
            return current_message, formatted_html
        except Exception:  # pylint: disable=broad-exception-caught
            # If HTML fails, try plain text in next iteration
            continue

    # Both attempts failed, return unchanged
    return current_message, last_sent_text


def _strip_html(text: str) -> str:
    """Remove HTML tags from text, keeping content.

    Simple regex-based stripping for fallback when HTML parsing fails.

    Args:
        text: Text potentially containing HTML tags.

    Returns:
        Plain text without HTML tags.
    """
    # Remove HTML tags but keep content
    clean = re.sub(r'<[^>]+>', '', text)
    # Unescape common HTML entities
    clean = clean.replace('&lt;', '<').replace('&gt;',
                                               '>').replace('&amp;', '&')
    return clean


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
            wait_time = min(e.retry_after, 30)  # Cap at 30 seconds
            logger.warning("telegram.flood_control",
                           retry_after=e.retry_after,
                           wait_time=wait_time,
                           attempt=attempt + 1)
            await asyncio.sleep(wait_time)
    raise TelegramRetryAfter(retry_after=0,
                             method="send_with_retry",
                             message="Max retries")


async def _update_telegram_message(  # pylint: disable=too-many-return-statements
    text: str,
    current_message: types.Message | None,
    first_message: types.Message,
    all_messages: list[types.Message],
    last_sent_text: str,
) -> tuple[types.Message | None, str]:
    """Update or send Telegram message with accumulated text.

    Handles message splitting when text exceeds 4000 chars.
    Skips update if text hasn't changed.

    Args:
        text: Accumulated text to display.
        current_message: Current message being edited (or None).
        first_message: Original user message (for reply).
        all_messages: List to track all sent messages.
        last_sent_text: Previously sent text (to avoid duplicate edits).

    Returns:
        Tuple of (current_message, new_last_sent_text).
    """
    # Skip if nothing changed
    if text == last_sent_text:
        return current_message, last_sent_text

    # Escape HTML for Telegram
    safe_text = safe_html(text)

    # Check if we need to split (Telegram limit ~4096)
    if len(safe_text) > MESSAGE_SPLIT_LENGTH:
        # Find split point in ORIGINAL text to avoid position mismatch
        # Estimate position (may need adjustment due to HTML escaping)
        estimated_pos = min(MESSAGE_SPLIT_LENGTH - 300,
                            len(text))  # Conservative

        # Try paragraph boundary first
        para_pos = text.rfind('\n\n', 0, estimated_pos)
        if para_pos > estimated_pos - TEXT_SPLIT_PARA_WINDOW and para_pos > 0:
            split_pos = para_pos + 1
        # Fall back to single newline
        elif (newline_pos := text.rfind(
                '\n', 0,
                estimated_pos)) > estimated_pos - TEXT_SPLIT_LINE_WINDOW:
            if newline_pos > 0:
                split_pos = newline_pos
            else:
                split_pos = estimated_pos
        else:
            split_pos = estimated_pos

        # Adjust if escaped version is still too long
        while len(safe_html(
                text[:split_pos])) > MESSAGE_SPLIT_LENGTH and split_pos > 100:
            newline_pos = text.rfind('\n', 0, split_pos - 1)
            if newline_pos > 0:
                split_pos = newline_pos
            else:
                split_pos = int(split_pos * 0.9)

        # Split text
        first_part = text[:split_pos]
        remaining = text[split_pos:].lstrip()  # Remove leading whitespace

        if current_message:
            try:
                await current_message.edit_text(safe_html(first_part))
            except Exception:  # pylint: disable=broad-exception-caught
                pass

        # Start new message with remaining text
        try:
            new_msg = await first_message.answer(safe_html(remaining))
            all_messages.append(new_msg)
            return new_msg, text
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("stream.message_send_failed", error=str(e))
            return current_message, last_sent_text

    else:
        # Normal update - no splitting needed
        if current_message:
            try:
                await current_message.edit_text(safe_text)
                return current_message, text
            except Exception:  # pylint: disable=broad-exception-caught
                # Edit failed, but message exists - content might be same
                return current_message, last_sent_text
        else:
            # First message
            try:
                new_msg = await first_message.answer(safe_text)
                all_messages.append(new_msg)
                return new_msg, text
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("stream.message_send_failed", error=str(e))
                return None, last_sent_text


async def _process_generated_files(
    result: dict,
    first_message: types.Message,
    _thread_id: int,
    _session: AsyncSession,
    user_file_repo: UserFileRepository,
    chat_id: int,
    user_id: int,
    telegram_thread_id: int | None,
) -> None:
    """Process and deliver files generated by tools.

    Extracted from _handle_with_tools for reuse.
    """
    file_contents = result.pop("_file_contents")
    delivered_files = []  # List of {filename, claude_file_id, file_type}

    for file_data in file_contents:
        try:
            filename = file_data["filename"]
            file_bytes = file_data["content"]
            mime_type = file_data["mime_type"]

            # Upload to Files API
            claude_file_id = await upload_to_files_api(file_bytes=file_bytes,
                                                       filename=filename,
                                                       mime_type=mime_type)

            # Determine file type
            if mime_type.startswith("image/"):
                file_type = FileType.IMAGE
            elif mime_type == "application/pdf":
                file_type = FileType.PDF
            else:
                file_type = FileType.DOCUMENT

            # Send to Telegram
            telegram_file_id = None
            telegram_file_unique_id = None

            if file_type == FileType.IMAGE and mime_type in [
                    "image/jpeg", "image/png", "image/gif", "image/webp"
            ]:
                sent_msg = await first_message.bot.send_photo(
                    chat_id=chat_id,
                    photo=types.BufferedInputFile(file_bytes,
                                                  filename=filename),
                    message_thread_id=telegram_thread_id)
                if sent_msg.photo:
                    largest = max(sent_msg.photo,
                                  key=lambda p: p.file_size or 0)
                    telegram_file_id = largest.file_id
                    telegram_file_unique_id = largest.file_unique_id
            else:
                sent_msg = await first_message.bot.send_document(
                    chat_id=chat_id,
                    document=types.BufferedInputFile(file_bytes,
                                                     filename=filename),
                    message_thread_id=telegram_thread_id)
                if sent_msg.document:
                    telegram_file_id = sent_msg.document.file_id
                    telegram_file_unique_id = sent_msg.document.file_unique_id

            # Save to database
            await user_file_repo.create(
                message_id=first_message.message_id,
                telegram_file_id=telegram_file_id,
                telegram_file_unique_id=telegram_file_unique_id,
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

            # Store file info with claude_file_id for tool result
            delivered_files.append({
                "filename": filename,
                "claude_file_id": claude_file_id,
                "file_type": file_type.value,
            })

            # Dashboard tracking event (must match Grafana query)
            logger.info("files.bot_file_sent",
                        user_id=user_id,
                        file_type=file_type.value,
                        filename=filename)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("stream.file_delivery_failed",
                         filename=file_data.get("filename"),
                         error=str(e),
                         exc_info=True)

    if delivered_files:
        # Format result with claude_file_id so Claude can reference files
        file_list = "\n".join(f"- {f['filename']} ({f['file_type']}): "
                              f"claude_file_id={f['claude_file_id']}"
                              for f in delivered_files)
        result["files_delivered"] = (
            f"Successfully sent {len(delivered_files)} file(s) to user:\n"
            f"{file_list}\n\n"
            f"Use these claude_file_id values with analyze_image or "
            f"analyze_pdf tools if you need to analyze the files.")


async def _charge_for_tool(
    session: AsyncSession,
    user_id: int,
    tool_name: str,
    result: dict,
    message_id: int,
) -> None:
    """Charge user for tool execution cost."""
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
    max_iterations = TOOL_LOOP_MAX_ITERATIONS
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
                                claude_file_id = await upload_to_files_api(
                                    file_bytes=file_bytes,
                                    filename=filename,
                                    mime_type=mime_type)

                                # 2. Send to Telegram user FIRST
                                # (to get telegram_file_id for database)
                                # Send as photo if image, otherwise as document
                                # IMPORTANT: Include message_thread_id for forum topics
                                # Determine file type
                                if mime_type.startswith("image/"):
                                    file_type = FileType.IMAGE
                                elif mime_type == "application/pdf":
                                    file_type = FileType.PDF
                                else:
                                    file_type = FileType.DOCUMENT

                                telegram_file_id = None
                                telegram_file_unique_id = None

                                if file_type == FileType.IMAGE and mime_type in [
                                        "image/jpeg", "image/png", "image/gif",
                                        "image/webp"
                                ]:
                                    sent_msg = await first_message.bot.send_photo(
                                        chat_id=chat_id,
                                        photo=types.BufferedInputFile(
                                            file_bytes, filename=filename),
                                        message_thread_id=telegram_thread_id)
                                    # Extract file_id from sent photo
                                    if sent_msg.photo:
                                        # Get largest photo size
                                        largest = max(
                                            sent_msg.photo,
                                            key=lambda p: p.file_size or 0)
                                        telegram_file_id = largest.file_id
                                        telegram_file_unique_id = (
                                            largest.file_unique_id)
                                else:
                                    sent_msg = await first_message.bot.send_document(
                                        chat_id=chat_id,
                                        document=types.BufferedInputFile(
                                            file_bytes, filename=filename),
                                        message_thread_id=telegram_thread_id)
                                    # Extract file_id from sent document
                                    if sent_msg.document:
                                        telegram_file_id = (
                                            sent_msg.document.file_id)
                                        telegram_file_unique_id = (
                                            sent_msg.document.file_unique_id)

                                # 3. Save to database (source=ASSISTANT)
                                # Now with telegram_file_id for future downloads
                                await user_file_repo.create(
                                    message_id=first_message.message_id,
                                    telegram_file_id=telegram_file_id,
                                    telegram_file_unique_id=
                                    telegram_file_unique_id,
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

                                delivered_files.append(filename)

                                logger.info(
                                    "tools.loop.generated_file_delivered",
                                    filename=filename,
                                    claude_file_id=claude_file_id,
                                    file_type=file_type.value)

                                # Dashboard tracking event
                                logger.info("files.bot_file_sent",
                                            user_id=user_id,
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
                    record_tool_call(tool_name=tool_name,
                                     success=True,
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
                    record_tool_call(tool_name=tool_name,
                                     success=False,
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
            request = LLMRequest(
                messages=context,
                system_prompt=composed_prompt,
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
            logger.info("claude_handler.unified_streaming",
                        thread_id=thread_id,
                        tool_count=len(request.tools) if request.tools else 0)

            try:
                response_text, all_messages = await _stream_with_unified_events(
                    request=request,
                    first_message=first_message,
                    thread_id=thread_id,
                    session=session,
                    user_file_repo=user_file_repo,
                    chat_id=thread.chat_id,
                    user_id=thread.user_id,
                    telegram_thread_id=thread.thread_id,
                )

                # Cleanup: delete ALL thinking/tool messages, send fresh final answer
                if all_messages:
                    for msg in all_messages:
                        try:
                            await msg.delete()
                        except Exception as del_err:  # pylint: disable=broad-exception-caught
                            logger.warning(
                                "claude_handler.cleanup_delete_failed",
                                message_id=msg.message_id,
                                error=str(del_err))

                    logger.info("claude_handler.cleanup_complete",
                                thread_id=thread_id,
                                deleted_count=len(all_messages))

                # Send final answer as new message(s)
                # Strip tool markers (shown during streaming, not in final answer)
                bot_message = None
                clean_response = strip_tool_markers(
                    response_text) if response_text else ""

                if clean_response:
                    safe_final = safe_html(clean_response)

                    # Split using smart boundaries (paragraph > newline > hard split)
                    chunks = split_text_smart(safe_final)
                    for chunk in chunks:
                        bot_message = await _send_with_retry(
                            first_message, chunk)
                else:
                    logger.warning("claude_handler.empty_response",
                                   thread_id=thread_id)
                    bot_message = await _send_with_retry(
                        first_message, "⚠️ Claude returned an empty response. "
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

            # 9. Get usage stats, stop_reason, thinking, and calculate cost
            usage = await claude_provider.get_usage()
            stop_reason = claude_provider.get_stop_reason()
            thinking = claude_provider.get_thinking(
            )  # Phase 1.4.3: Extended Thinking

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

            logger.info("claude_handler.response_complete",
                        thread_id=thread_id,
                        model_id=user.model_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        thinking_tokens=usage.thinking_tokens,
                        cache_read_tokens=usage.cache_read_tokens,
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

    # Record metrics
    content_type = "text"
    if message.photo:
        content_type = "photo"
    elif message.document:
        content_type = "document"
    record_message_received(chat_type=message.chat.type,
                            content_type=content_type)

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
            added_to_attachment_menu=(message.from_user.added_to_attachment_menu
                                      or False),
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
            or message.from_user.first_name if message.from_user else None)

        thread, was_created = await thread_repo.get_or_create_thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=message.message_thread_id,  # Telegram forum thread ID
            title=thread_title,
        )

        if was_created:
            logger.info("claude_handler.thread_created",
                        thread_id=thread.id,
                        user_id=user.id,
                        telegram_thread_id=message.message_thread_id)

        # Log message received (after thread resolution to know is_new_thread)
        logger.info("claude_handler.message_received",
                    chat_id=message.chat.id,
                    user_id=message.from_user.id if message.from_user else None,
                    message_id=message.message_id,
                    message_thread_id=message.message_thread_id,
                    is_topic_message=message.is_topic_message,
                    text_length=len(message.text or message.caption or ""),
                    is_new_thread="true" if was_created else "false")

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
