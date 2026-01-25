"""Middleware for logging user interactions and registering topics.

This middleware:
1. Logs all slash commands (/help, /balance, /clear, etc.) with details
2. Logs callback button presses with callback_data
3. Creates a thread record in the DB when a command is sent in a topic

The thread registration ensures that /clear knows when a topic already has
activity (even if that activity was only commands, not regular messages).

NO __init__.py - use direct import:
    from telegram.middlewares.command_middleware import CommandMiddleware
    from telegram.middlewares.command_middleware import CallbackLoggingMiddleware
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram import types
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class CommandMiddleware(BaseMiddleware):
    """Middleware that logs commands and registers topics in DB.

    Runs BEFORE command handlers to ensure topic is registered
    before any command logic executes.
    """

    async def __call__(
        self,
        handler: Callable[[types.Message, dict[str, Any]], Awaitable[Any]],
        event: types.Message,
        data: dict[str, Any],
    ) -> Any:
        """Process message - log if command and register topic.

        Args:
            handler: Next handler in chain.
            event: Telegram message.
            data: Middleware data (includes session).

        Returns:
            Result from next handler.
        """
        # Only process messages with text that start with /
        if not event.text or not event.text.startswith("/"):
            return await handler(event, data)

        # Extract command name (first word without /)
        command_parts = event.text.split()
        command_name = command_parts[0][1:]  # Remove leading /
        # Handle commands with @bot_username suffix
        if "@" in command_name:
            command_name = command_name.split("@")[0]
        command_args = " ".join(
            command_parts[1:]) if len(command_parts) > 1 else ""

        user_id = event.from_user.id if event.from_user else None
        chat_id = event.chat.id
        topic_id = event.message_thread_id

        # Log the command with full details
        logger.info(
            "user.command",
            command=command_name,
            args=command_args[:100]
            if command_args else None,  # Truncate long args
            user_id=user_id,
            chat_id=chat_id,
            topic_id=topic_id,
            message_id=event.message_id,
        )

        # Register topic in DB if we're in a topic
        # This ensures /clear knows the topic has activity
        if topic_id and user_id:
            session: AsyncSession | None = data.get("session")
            if session:
                await self._ensure_topic_registered(
                    session=session,
                    event=event,
                    chat_id=chat_id,
                    user_id=user_id,
                    topic_id=topic_id,
                )

        return await handler(event, data)

    async def _ensure_topic_registered(
        self,
        session: AsyncSession,
        event: types.Message,
        chat_id: int,
        user_id: int,
        topic_id: int,
    ) -> None:
        """Ensure topic has a thread record in DB.

        Creates user, chat, and thread records if they don't exist.
        This is lightweight - only creates minimal records.

        Args:
            session: Database session.
            event: Telegram message (for user info).
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            topic_id: Telegram topic/thread ID.
        """
        try:
            # Ensure user exists (required for thread foreign key)
            user_repo = UserRepository(session)
            user = await user_repo.get_by_telegram_id(user_id)
            if not user and event.from_user:
                # Create minimal user record
                user, _ = await user_repo.get_or_create(
                    telegram_id=user_id,
                    is_bot=event.from_user.is_bot,
                    first_name=event.from_user.first_name,
                    last_name=event.from_user.last_name,
                    username=event.from_user.username,
                    language_code=event.from_user.language_code,
                    is_premium=event.from_user.is_premium or False,
                    added_to_attachment_menu=(
                        event.from_user.added_to_attachment_menu or False),
                )
                logger.debug(
                    "command.user_created",
                    user_id=user_id,
                )

            # Ensure chat exists (get_or_create handles both cases)
            chat_repo = ChatRepository(session)
            chat, chat_created = await chat_repo.get_or_create(
                telegram_id=chat_id,
                chat_type="private",  # Assume private for commands
                is_forum=True,  # Has topics
            )
            if chat_created:
                logger.debug(
                    "command.chat_created",
                    chat_id=chat_id,
                )

            # Ensure thread exists for this topic (get_or_create_thread)
            # Uses Telegram IDs directly since models use them as PKs
            thread_repo = ThreadRepository(session)
            thread, thread_created = await thread_repo.get_or_create_thread(
                chat_id=chat_id,  # Telegram chat ID = Chat.id
                user_id=user_id,  # Telegram user ID = User.id
                thread_id=topic_id,  # Telegram topic ID
            )
            if thread_created:
                logger.debug(
                    "command.topic_registered",
                    chat_id=chat_id,
                    topic_id=topic_id,
                    thread_id=thread.id,
                )

            # Commit all changes
            await session.commit()

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Don't fail command if topic registration fails
            logger.warning(
                "command.topic_registration_failed",
                chat_id=chat_id,
                topic_id=topic_id,
                error=str(e),
            )


class CallbackLoggingMiddleware(BaseMiddleware):
    """Middleware that logs callback button presses.

    Logs the callback_data when users press inline keyboard buttons.
    """

    async def __call__(
        self,
        handler: Callable[[types.CallbackQuery, dict[str, Any]],
                          Awaitable[Any]],
        event: types.CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        """Process callback query - log button press.

        Args:
            handler: Next handler in chain.
            event: Telegram callback query.
            data: Middleware data.

        Returns:
            Result from next handler.
        """
        user_id = event.from_user.id if event.from_user else None
        chat_id = event.message.chat.id if event.message else None
        callback_data = event.data or ""

        # Parse callback_data to extract action type
        # Common format: "action:value" or "prefix_action"
        action = callback_data.split(
            ":")[0] if ":" in callback_data else callback_data

        logger.info(
            "user.callback",
            action=action,
            callback_data=callback_data[:100],  # Truncate long data
            user_id=user_id,
            chat_id=chat_id,
            callback_id=event.id,
        )

        return await handler(event, data)
