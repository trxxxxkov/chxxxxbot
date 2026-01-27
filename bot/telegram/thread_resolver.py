"""Thread resolution helper for Telegram messages.

This module provides the get_or_create_thread helper function used by
the unified pipeline to resolve database threads.

NO __init__.py - use direct import:
    from telegram.thread_resolver import get_or_create_thread
"""

from aiogram import types
from db.models.thread import Thread
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


async def get_or_create_thread(message: types.Message,
                               session: AsyncSession) -> Thread:
    """Get or create thread for message.

    Used by the unified pipeline to resolve database threads.
    Creates user and chat records if they don't exist.

    Args:
        message: Telegram message.
        session: Database session.

    Returns:
        Thread for this message.

    Raises:
        ValueError: Missing from_user or chat.
    """
    if not message.from_user:
        raise ValueError("Message has no from_user")

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Get or create user
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(
        telegram_id=user_id,
        is_bot=message.from_user.is_bot,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code,
        is_premium=message.from_user.is_premium or False,
        added_to_attachment_menu=(message.from_user.added_to_attachment_menu or
                                  False),
    )

    # Get or create chat
    chat_repo = ChatRepository(session)
    chat, _ = await chat_repo.get_or_create(
        telegram_id=chat_id,
        chat_type=message.chat.type,
        title=message.chat.title,
        username=message.chat.username,
        first_name=message.chat.first_name,
        last_name=message.chat.last_name,
        is_forum=message.chat.is_forum or False,
    )

    # Get or create thread
    thread_repo = ThreadRepository(session)

    # Generate thread title from chat/user info
    thread_title = (
        message.chat.title  # Groups/supergroups
        or message.chat.first_name  # Private chats
        or message.from_user.first_name if message.from_user else None)

    thread, was_created = await thread_repo.get_or_create_thread(
        chat_id=chat_id,
        user_id=user_id,
        thread_id=message.message_thread_id,
        title=thread_title,
    )

    # Dashboard tracking events
    if was_created:
        logger.info("claude_handler.thread_created",
                    thread_id=thread.id,
                    user_id=user_id,
                    telegram_thread_id=message.message_thread_id)

        # Bot API 9.3: Set needs_topic_naming for new topics
        # Topics exist in: private chats with topics enabled, or forum supergroups
        if message.message_thread_id is not None:
            thread.needs_topic_naming = True
            logger.debug(
                "thread_resolver.topic_needs_naming",
                thread_id=thread.id,
                telegram_thread_id=message.message_thread_id,
            )

    # Log message received for dashboard tracking
    logger.info("claude_handler.message_received",
                chat_id=chat_id,
                user_id=user_id,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                is_topic_message=message.is_topic_message,
                text_length=len(message.text or message.caption or ""),
                is_new_thread="true" if was_created else "false")

    logger.debug("thread_resolver.thread_resolved",
                 user_id=user_id,
                 chat_id=chat_id,
                 thread_id=thread.id,
                 telegram_thread_id=message.message_thread_id)

    return thread
