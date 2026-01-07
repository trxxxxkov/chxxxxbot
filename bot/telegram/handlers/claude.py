"""Claude conversation handler.

This module handles all text messages from users, sends them to Claude API,
and streams responses back to Telegram in real-time.

NO __init__.py - use direct import: from telegram.handlers.claude import router
"""

from aiogram import F
from aiogram import Router
from aiogram import types
import config
from config import CLAUDE_MODELS
from config import CLAUDE_TOKEN_BUFFER_PERCENT
from config import DEFAULT_MODEL
from config import GLOBAL_SYSTEM_PROMPT
from core.claude.client import ClaudeProvider
from core.claude.context import ContextManager
from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import ContextWindowExceededError
from core.exceptions import LLMError
from core.exceptions import RateLimitError
from core.models import LLMRequest
from core.models import Message
from db.models.message import MessageRole
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Create router with name
router = Router(name="claude")

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


@router.message(F.text)
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
async def handle_claude_message(message: types.Message,
                                session: AsyncSession) -> None:
    """Handle text message and generate Claude response.

    Flow:
    1. Save user message to database
    2. Get or create thread
    3. Build context from thread history
    4. Stream response from Claude
    5. Send/update message in Telegram
    6. Save Claude response to database

    Args:
        message: Incoming Telegram message.
        session: Database session (injected by middleware).
    """
    if claude_provider is None:
        logger.error("claude_handler.provider_not_initialized")
        await message.answer(
            "Bot is not properly configured. Please contact administrator.")
        return

    logger.info("claude_handler.message_received",
                chat_id=message.chat.id,
                user_id=message.from_user.id if message.from_user else None,
                message_id=message.message_id,
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

        # 3. Get or create thread
        thread_repo = ThreadRepository(session)
        thread, was_created = await thread_repo.get_or_create_thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=None,  # Phase 1.3: no forum threads yet
            model_name=DEFAULT_MODEL,
        )

        if was_created:
            logger.info("claude_handler.thread_created", thread_id=thread.id)

        # 4. Save user message
        msg_repo = MessageRepository(session)
        await msg_repo.create_message(
            chat_id=chat.id,
            message_id=message.message_id,
            thread_id=thread.id,
            from_user_id=user.id,
            date=message.date.timestamp(),
            role=MessageRole.USER,
            text_content=message.text,
        )

        logger.debug("claude_handler.user_message_saved",
                     message_id=message.message_id)

        # 5. Get thread history
        history = await msg_repo.get_thread_messages(thread.id)

        logger.debug("claude_handler.history_retrieved",
                     thread_id=thread.id,
                     message_count=len(history))

        # 6. Build context
        context_mgr = ContextManager(claude_provider)

        # Get model config
        model_config = CLAUDE_MODELS[DEFAULT_MODEL]

        # Convert DB messages to LLM messages
        llm_messages = [
            Message(role="user" if msg.from_user_id else "assistant",
                    content=msg.text_content) for msg in history
        ]

        context = await context_mgr.build_context(
            messages=llm_messages,
            model_context_window=model_config.context_window,
            system_prompt=GLOBAL_SYSTEM_PROMPT,
            max_output_tokens=config.CLAUDE_MAX_TOKENS,
            buffer_percent=CLAUDE_TOKEN_BUFFER_PERCENT)

        logger.info("claude_handler.context_built",
                    included_messages=len(context),
                    total_messages=len(llm_messages))

        # 7. Prepare Claude request
        request = LLMRequest(messages=context,
                             system_prompt=GLOBAL_SYSTEM_PROMPT,
                             model=model_config.name,
                             max_tokens=config.CLAUDE_MAX_TOKENS,
                             temperature=config.CLAUDE_TEMPERATURE)

        # 8. Show typing indicator
        await message.bot.send_chat_action(message.chat.id, "typing")

        # 9. Stream response (no buffering - update on every chunk)
        response_text = ""
        last_sent_text = ""  # Track last sent text to avoid redundant edits
        bot_message = None

        async for chunk in claude_provider.stream_message(request):
            response_text += chunk

            # Check if message needs to be split
            if len(response_text) > 4000:
                # Send current part and start new message
                text_to_send = response_text[:4000]

                if bot_message is None:
                    bot_message = await message.answer(text_to_send)
                    last_sent_text = text_to_send
                elif text_to_send != last_sent_text:
                    try:
                        await bot_message.edit_text(text_to_send)
                        last_sent_text = text_to_send
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.warning("claude_handler.edit_failed",
                                       error=str(e))

                # Start new message with remaining text
                response_text = response_text[4000:]
                bot_message = None
                last_sent_text = ""
            else:
                # Update message with every chunk (no buffering)
                if bot_message is None:
                    bot_message = await message.answer(response_text)
                    last_sent_text = response_text
                elif response_text != last_sent_text:
                    try:
                        await bot_message.edit_text(response_text)
                        last_sent_text = response_text
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.warning("claude_handler.edit_failed",
                                       error=str(e))

        # Final update if there's remaining text
        if response_text:
            if bot_message is None:
                bot_message = await message.answer(response_text)
            elif response_text != last_sent_text:
                try:
                    await bot_message.edit_text(response_text)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("claude_handler.final_edit_failed",
                                   error=str(e))
                    # If edit fails, send as new message
                    bot_message = await message.answer(response_text)

        if not bot_message:
            logger.error("claude_handler.no_bot_message")
            await message.answer("Failed to send response.")
            return

        # 10. Get usage stats
        usage = await claude_provider.get_usage()

        logger.info("claude_handler.response_complete",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    response_length=len(response_text))

        # 11. Save Claude response
        await msg_repo.create_message(
            chat_id=chat.id,
            message_id=bot_message.message_id,
            thread_id=thread.id,
            from_user_id=None,  # Bot message
            date=bot_message.date.timestamp(),
            role=MessageRole.ASSISTANT,
            text_content=response_text,
        )

        # 12. Add token usage for billing
        await msg_repo.add_tokens(
            chat_id=chat.id,
            message_id=bot_message.message_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        logger.info("claude_handler.bot_message_saved",
                    message_id=bot_message.message_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens)

    except ContextWindowExceededError as e:
        logger.error("claude_handler.context_exceeded",
                     tokens_used=e.tokens_used,
                     tokens_limit=e.tokens_limit,
                     exc_info=True)

        await message.answer(
            f"⚠️ Context window exceeded.\n\n"
            f"Your conversation is too long ({e.tokens_used:,} tokens). "
            f"Please start a new thread or reduce message history.")

    except RateLimitError as e:
        logger.error("claude_handler.rate_limit",
                     error=str(e),
                     retry_after=e.retry_after,
                     exc_info=True)

        retry_msg = ""
        if e.retry_after:
            retry_msg = f"\n\nPlease try again in {e.retry_after} seconds."

        await message.answer(
            f"⚠️ Rate limit exceeded.{retry_msg}\n\n"
            f"Too many requests. Please wait a moment and try again.")

    except APIConnectionError as e:
        logger.error("claude_handler.connection_error",
                     error=str(e),
                     exc_info=True)

        await message.answer(
            "⚠️ Connection error.\n\n"
            "Failed to connect to Claude API. Please check your internet "
            "connection and try again.")

    except APITimeoutError as e:
        logger.error("claude_handler.timeout", error=str(e), exc_info=True)

        await message.answer(
            "⚠️ Request timed out.\n\n"
            "The request took too long. Please try again with a shorter "
            "message or simpler question.")

    except LLMError as e:
        logger.error("claude_handler.llm_error",
                     error=str(e),
                     error_type=type(e).__name__,
                     exc_info=True)

        await message.answer(
            f"⚠️ Error: {str(e)}\n\n"
            f"Please try again or contact administrator if the problem "
            f"persists.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("claude_handler.unexpected_error",
                     error=str(e),
                     error_type=type(e).__name__,
                     exc_info=True)

        await message.answer("⚠️ Unexpected error occurred.\n\n"
                             "Please try again or contact administrator.")
