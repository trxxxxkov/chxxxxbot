"""Handlers for /model command and model selection.

This module contains handlers for model selection:
- /model command shows current model and keyboard
- Callback handlers for model selection
"""

from aiogram import F
from aiogram import Router
from aiogram import types
from aiogram.filters import Command
from config import get_default_model
from config import get_model
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.keyboards.model_selector import format_model_info
from telegram.keyboards.model_selector import get_model_keyboard
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="model")


@router.message(Command("model"))
async def model_command(  # pylint: disable=too-many-locals
        message: types.Message, session: AsyncSession) -> None:
    """Handles /model command.

    Shows current model and inline keyboard for selecting new model.
    Creates thread if doesn't exist yet.

    Args:
        message: Incoming Telegram message with /model command.
        session: Database session injected by DatabaseMiddleware.
    """
    if not message.from_user or not message.chat:
        await message.answer("⚠️ Unable to identify user or chat.")
        return

    user = message.from_user
    chat = message.chat

    # Get repositories
    user_repo = UserRepository(session)
    chat_repo = ChatRepository(session)
    thread_repo = ThreadRepository(session)

    # Ensure user exists
    db_user, _ = await user_repo.get_or_create(
        telegram_id=user.id,
        is_bot=user.is_bot,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=user.is_premium or False,
        added_to_attachment_menu=user.added_to_attachment_menu or False,
    )

    # Ensure chat exists
    db_chat, _ = await chat_repo.get_or_create(
        telegram_id=chat.id,
        chat_type=chat.type,
        title=chat.title,
        username=chat.username,
        first_name=chat.first_name,
        last_name=chat.last_name,
        is_forum=chat.is_forum or False,
    )

    # Get or create thread
    # For private chats, always use thread_id=None (single conversation per user)
    # For forum chats, use message.message_thread_id (forum topic ID)
    thread_id = None if chat.type == "private" else message.message_thread_id
    db_thread, was_created = await thread_repo.get_or_create_thread(
        chat_id=db_chat.id,
        user_id=db_user.id,
        thread_id=thread_id,
        title=None,  # Will be set later if needed
    )

    if was_created:
        logger.info("thread.created",
                    thread_id=db_thread.id,
                    user_id=db_user.id,
                    chat_id=db_chat.id,
                    telegram_thread_id=thread_id)

    # Get current model info from user (Phase 1.4.1: model is per user)
    try:
        current_model = get_model(db_user.model_id)
    except KeyError:
        # Fallback to default if user has invalid model_id
        logger.warning("user.invalid_model_id",
                       user_id=db_user.id,
                       invalid_model_id=db_user.model_id)
        current_model = get_default_model()
        db_user.model_id = current_model.get_full_id()
        await session.commit()

    # Format message
    message_text = "🤖 Model Selection\n\n"
    message_text += "**Current model:**\n"
    message_text += format_model_info(current_model)
    message_text += "\n\n👇 Select new model:"

    # Send keyboard
    keyboard = get_model_keyboard(current=db_user.model_id)

    logger.info("model_command",
                user_id=user.id,
                chat_id=chat.id,
                thread_id=db_thread.id,
                current_model=db_user.model_id)

    await message.answer(message_text,
                         reply_markup=keyboard.as_markup(),
                         parse_mode="Markdown")


@router.callback_query(F.data.startswith("model:"))
async def model_selection_callback(  # pylint: disable=too-many-locals
        callback: types.CallbackQuery, session: AsyncSession) -> None:
    """Handles model selection from inline keyboard.

    Args:
        callback: Callback query from inline keyboard.
        session: Database session injected by DatabaseMiddleware.
    """
    if not callback.data or not callback.message or not callback.from_user:
        await callback.answer("⚠️ Invalid callback data")
        return

    # Parse model_id from callback data
    # Format: "model:claude:sonnet" -> "claude:sonnet"
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("⚠️ Invalid model selection")
        return

    new_model_id = parts[1]

    # Validate model
    try:
        new_model = get_model(new_model_id)
    except KeyError:
        logger.error("model_selection.invalid_model",
                     model_id=new_model_id,
                     user_id=callback.from_user.id)
        await callback.answer(f"⚠️ Model '{new_model_id}' not found")
        return

    user = callback.from_user

    # Get repositories
    user_repo = UserRepository(session)

    # Get user
    db_user = await user_repo.get_by_telegram_id(user.id)
    if not db_user:
        await callback.answer("⚠️ User not found")
        return

    # Update user model (Phase 1.4.1: model is per user, not per thread)
    old_model_id = db_user.model_id
    db_user.model_id = new_model_id
    await session.commit()

    logger.info("model.changed",
                user_id=db_user.id,
                old_model=old_model_id,
                new_model=new_model_id)

    # Update message
    success_text = "✅ **Model changed**\n\n"
    success_text += format_model_info(new_model)

    await callback.message.edit_text(success_text, parse_mode="Markdown")
    await callback.answer(f"Model changed to {new_model.display_name}")


@router.callback_query(F.data == "noop")
async def noop_callback(callback: types.CallbackQuery) -> None:
    """Handles no-op callbacks (section headers in keyboards).

    Args:
        callback: Callback query to acknowledge.
    """
    await callback.answer()
