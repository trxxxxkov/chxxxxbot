"""Claude conversation handler.

This module handles all text messages from users, sends them to Claude API,
and streams responses back to Telegram in real-time.

NO __init__.py - use direct import: from telegram.handlers.claude import router
"""

import time

from aiogram import F
from aiogram import Router
from aiogram import types
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
from core.tools import execute_tool
from core.tools import TOOL_DEFINITIONS
from core.tools.helpers import extract_tool_uses
from core.tools.helpers import format_files_section
from core.tools.helpers import format_tool_results
from core.tools.helpers import get_available_files
from db.engine import get_session
from db.models.message import MessageRole
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_file_repository import UserFileRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Create router with name
router = Router(name="claude")

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


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
async def _handle_with_tools(request: LLMRequest, first_message: types.Message,
                             thread_id: int) -> str:
    """Handle request with tool use loop.

    Implements tool use pattern:
    1. Call Claude API (non-streaming)
    2. Check stop_reason
    3. If tool_use: execute tools, add results, repeat
    4. If end_turn: return final text

    Args:
        request: LLMRequest with tools configured.
        first_message: First Telegram message (for status updates).
        thread_id: Thread ID for logging.

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
        iter_request = LLMRequest(messages=[
            Message(role=msg["role"], content=msg["content"])
            for msg in conversation
        ],
                                  system_prompt=request.system_prompt,
                                  model=request.model,
                                  max_tokens=request.max_tokens,
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

                # Execute tool
                try:
                    result = await execute_tool(tool_name, tool_input)
                    results.append(result)

                    logger.info("tools.loop.tool_success",
                                thread_id=thread_id,
                                tool_name=tool_name,
                                result_keys=list(result.keys()))

                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Tool execution failed - return error in tool_result
                    error_msg = f"Tool execution failed: {str(e)}"
                    results.append({"error": error_msg})

                    logger.error("tools.loop.tool_failed",
                                 thread_id=thread_id,
                                 tool_name=tool_name,
                                 error=str(e),
                                 exc_info=True)

            # Format tool results for API
            tool_results = format_tool_results(tool_uses, results)

            # Add assistant response + tool results to conversation
            # CRITICAL: Include ALL content blocks (thinking + tool_use)
            conversation.append({
                "role": "assistant",
                "content": response.content
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
async def _process_message_batch(thread_id: int,
                                 messages: list[types.Message]) -> None:
    """Process batch of messages for a thread.

    This function is called by MessageQueueManager when it's time to process
    accumulated messages. Creates its own database session and handles the
    complete flow from saving messages to streaming Claude response.

    Phase 1.4.3: Batch processing with smart accumulation.

    Args:
        thread_id: Database thread ID.
        messages: List of Telegram messages to process as one batch.
    """
    if not messages:
        logger.warning("claude_handler.empty_batch", thread_id=thread_id)
        return

    if claude_provider is None:
        logger.error("claude_handler.provider_not_initialized")
        # Send error to first message
        await messages[0].answer(
            "Bot is not properly configured. Please contact administrator.")
        return

    # Use first message for bot/chat context
    first_message = messages[0]

    logger.info("claude_handler.batch_received",
                thread_id=thread_id,
                batch_size=len(messages),
                message_lengths=[len(msg.text or "") for msg in messages],
                telegram_thread_id=first_message.message_thread_id)

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
            for message in messages:
                await msg_repo.create_message(
                    chat_id=thread.chat_id,
                    message_id=message.message_id,
                    thread_id=thread_id,
                    from_user_id=thread.user_id,
                    date=message.date.timestamp(),
                    role=MessageRole.USER,
                    text_content=message.text,
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
            user_file_repo = UserFileRepository(session)
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
                        has_files_context=thread.files_context is not None,
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
                max_output_tokens=config.CLAUDE_MAX_TOKENS,
                buffer_percent=CLAUDE_TOKEN_BUFFER_PERCENT)

            logger.info("claude_handler.context_built",
                        thread_id=thread_id,
                        included_messages=len(context),
                        total_messages=len(llm_messages))

            # 6. Prepare Claude request (Phase 1.5: add tools if files available)
            request = LLMRequest(
                messages=context,
                system_prompt=composed_prompt,
                model=user.model_id,
                max_tokens=config.CLAUDE_MAX_TOKENS,
                temperature=config.CLAUDE_TEMPERATURE,
                tools=TOOL_DEFINITIONS if available_files else None)

            logger.info("claude_handler.request_prepared",
                        thread_id=thread_id,
                        has_tools=request.tools is not None,
                        tool_count=len(request.tools) if request.tools else 0)

            # 7. Show typing indicator (only when starting processing)
            await first_message.bot.send_chat_action(first_message.chat.id,
                                                     "typing")

            # 8. Handle request (Phase 1.5: with or without tools)
            if request.tools:
                # Tool loop (non-streaming until final answer)
                logger.info("claude_handler.using_tools",
                            thread_id=thread_id,
                            tool_count=len(request.tools))

                try:
                    response_text = await _handle_with_tools(
                        request, first_message, thread_id)

                    # Send final response (no streaming, already processed)
                    bot_message = await first_message.answer(response_text)

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

                    # Check if message needs to be split
                    if len(response_text) > 4000:
                        text_to_send = response_text[:4000]

                        if bot_message is None:
                            bot_message = await first_message.answer(
                                text_to_send)
                            last_sent_text = text_to_send
                            last_edit_time = current_time
                        elif text_to_send != last_sent_text:
                            try:
                                await bot_message.edit_text(text_to_send)
                                last_sent_text = text_to_send
                                last_edit_time = current_time
                            except Exception as e:  # pylint: disable=broad-exception-caught
                                logger.warning("claude_handler.edit_failed",
                                               error=str(e))

                        # Start new message with remaining text
                        response_text = response_text[4000:]
                        bot_message = None
                        last_sent_text = ""
                        last_edit_time = 0.0
                    elif should_update:
                        if bot_message is None:
                            bot_message = await first_message.answer(
                                response_text)
                            last_sent_text = response_text
                            last_edit_time = current_time
                        elif response_text != last_sent_text:
                            try:
                                await bot_message.edit_text(response_text)
                                last_sent_text = response_text
                                last_edit_time = current_time
                            except Exception as e:  # pylint: disable=broad-exception-caught
                                logger.warning("claude_handler.edit_failed",
                                               error=str(e))

                # Final update if there's remaining text
                if response_text:
                    if bot_message is None:
                        bot_message = await first_message.answer(response_text)
                    elif response_text != last_sent_text:
                        try:
                            await bot_message.edit_text(response_text)
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

            # 9. Get usage stats, stop_reason, and calculate cost
            usage = await claude_provider.get_usage()
            stop_reason = claude_provider.get_stop_reason()

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

            # 10. Save Claude response
            await msg_repo.create_message(
                chat_id=thread.chat_id,
                message_id=bot_message.message_id,
                thread_id=thread_id,
                from_user_id=None,  # Bot message
                date=bot_message.date.timestamp(),
                role=MessageRole.ASSISTANT,
                text_content=response_text,
            )

            # 11. Add token usage for billing
            await msg_repo.add_tokens(
                chat_id=thread.chat_id,
                message_id=bot_message.message_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            await session.commit()

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

        await first_message.answer(
            "⚠️ Connection error.\n\n"
            "Failed to connect to Claude API. Please check your internet "
            "connection and try again.")

    except APITimeoutError as e:
        logger.error("claude_handler.timeout",
                     thread_id=thread_id,
                     error=str(e),
                     exc_info=True)

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

        await first_message.answer("⚠️ Unexpected error occurred.\n\n"
                                   "Please try again or contact administrator.")


@router.message(F.text)
async def handle_claude_message(message: types.Message,
                                session: AsyncSession) -> None:
    """Handle text message and add to processing queue.

    Phase 1.4.3: Per-thread message batching with smart accumulation.

    Flow:
    1. Get or create user, chat, thread
    2. Add message to thread's queue
    3. Queue manager decides when to process (immediately or after 300ms)

    Args:
        message: Incoming Telegram message.
        session: Database session (injected by middleware).
    """
    if message_queue_manager is None:
        logger.error("claude_handler.queue_not_initialized")
        await message.answer(
            "Bot is not properly configured. Please contact administrator.")
        return

    logger.info("claude_handler.message_received",
                chat_id=message.chat.id,
                user_id=message.from_user.id if message.from_user else None,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                is_topic_message=message.is_topic_message,
                text_length=len(message.text or ""))

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
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
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
        thread, was_created = await thread_repo.get_or_create_thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=message.message_thread_id,  # Telegram forum thread ID
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
