"""Handlers for /personality command and personality management.

This module contains handlers for personality (custom_prompt) management:
- /personality command shows current prompt and keyboard
- Callback handlers for view, edit, clear actions
- State handler for receiving new personality text

Phase 1.4.2: 3-level system prompt architecture
- GLOBAL_SYSTEM_PROMPT (always cached)
- User.custom_prompt (cached, set via /personality)
- Thread.files_context (NOT cached, auto-generated)
"""

from aiogram import F
from aiogram import Router
from aiogram import types
from aiogram.filters import Command
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.state import StatesGroup
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.keyboards.personality_selector import format_personality_info
from telegram.keyboards.personality_selector import get_personality_keyboard
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="personality")


class PersonalityStates(StatesGroup):
    """FSM states for personality editing."""

    waiting_for_text = State()


@router.message(Command("personality"))
async def personality_command(message: types.Message,
                              session: AsyncSession) -> None:
    """Handle /personality command.

    Shows current custom_prompt and inline keyboard for editing.

    Args:
        message: Incoming Telegram message with /personality command.
        session: Database session injected by DatabaseMiddleware.
    """
    if not message.from_user:
        await message.answer("⚠️ Unable to identify user.")
        return

    user_id = message.from_user.id

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user:
        # Create user if doesn't exist
        db_user, _ = await user_repo.get_or_create(
            telegram_id=user_id,
            is_bot=message.from_user.is_bot,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username,
            language_code=message.from_user.language_code,
            is_premium=message.from_user.is_premium or False,
        )
        await session.commit()

    # Format message
    message_text = "🎭 **Personality Settings**\n\n"
    message_text += "Your custom personality instructions will be added to "
    message_text += "every conversation with the bot.\n\n"
    message_text += "**Current personality:**\n"
    message_text += format_personality_info(db_user.custom_prompt)

    # Send keyboard
    keyboard = get_personality_keyboard(
        has_custom_prompt=db_user.custom_prompt is not None)

    logger.info("personality_command",
                user_id=user_id,
                has_custom_prompt=db_user.custom_prompt is not None)

    await message.answer(message_text,
                         reply_markup=keyboard.as_markup(),
                         parse_mode="Markdown")


@router.callback_query(F.data == "personality:view")
async def personality_view_callback(callback: types.CallbackQuery,
                                    session: AsyncSession) -> None:
    """Handle 'View Current' button.

    Shows full custom_prompt text without truncation.

    Args:
        callback: Callback query from inline keyboard.
        session: Database session injected by DatabaseMiddleware.
    """
    if not callback.from_user:
        await callback.answer("⚠️ Unable to identify user")
        return

    user_id = callback.from_user.id

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user or not db_user.custom_prompt:
        await callback.answer("❌ No personality set")
        return

    # Show full text (no truncation)
    view_text = "🎭 **Your Current Personality:**\n\n"
    view_text += f"```\n{db_user.custom_prompt}\n```"

    logger.info("personality.viewed", user_id=user_id)

    await callback.message.answer(view_text, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "personality:edit")
async def personality_edit_callback(callback: types.CallbackQuery,
                                    state: FSMContext,
                                    _session: AsyncSession) -> None:
    """Handle 'Edit' button.

    Enters state waiting for new personality text from user.

    Args:
        callback: Callback query from inline keyboard.
        state: FSM context for state management.
        session: Database session injected by DatabaseMiddleware.
    """
    if not callback.from_user:
        await callback.answer("⚠️ Unable to identify user")
        return

    # Enter waiting state
    await state.set_state(PersonalityStates.waiting_for_text)

    # Save user_id in state data
    await state.update_data(user_id=callback.from_user.id)

    logger.info("personality.edit_started", user_id=callback.from_user.id)

    await callback.message.answer(
        "✏️ **Enter your new personality instructions:**\n\n"
        "Send me a message with your desired personality. "
        "This will be added to every conversation.\n\n"
        "_Send /cancel to abort._")
    await callback.answer()


@router.message(StateFilter(PersonalityStates.waiting_for_text))
async def personality_text_received(message: types.Message, state: FSMContext,
                                    session: AsyncSession) -> None:
    """Handle new personality text from user.

    Saves new custom_prompt to database and exits state.

    Args:
        message: User message with new personality text.
        state: FSM context for state management.
        session: Database session injected by DatabaseMiddleware.
    """
    if not message.text or not message.from_user:
        await message.answer("⚠️ Please send text message")
        return

    user_id = message.from_user.id
    new_prompt = message.text.strip()

    # Validate length (optional, but good practice)
    if len(new_prompt) < 10:
        await message.answer(
            "⚠️ Personality text too short. Please provide at least 10 characters."
        )
        return

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user:
        await message.answer("⚠️ User not found")
        await state.clear()
        return

    # Update custom_prompt
    old_prompt = db_user.custom_prompt
    db_user.custom_prompt = new_prompt
    await session.commit()

    logger.info("personality.updated",
                user_id=user_id,
                had_previous=old_prompt is not None,
                new_length=len(new_prompt))

    # Clear state
    await state.clear()

    # Confirmation
    success_text = "✅ **Personality updated successfully!**\n\n"
    success_text += "Your new personality:\n"
    success_text += format_personality_info(new_prompt, truncate=300)

    await message.answer(success_text, parse_mode="Markdown")


@router.callback_query(F.data == "personality:clear")
async def personality_clear_callback(callback: types.CallbackQuery,
                                     session: AsyncSession) -> None:
    """Handle 'Clear' button.

    Removes custom_prompt from user.

    Args:
        callback: Callback query from inline keyboard.
        session: Database session injected by DatabaseMiddleware.
    """
    if not callback.from_user:
        await callback.answer("⚠️ Unable to identify user")
        return

    user_id = callback.from_user.id

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user:
        await callback.answer("⚠️ User not found")
        return

    # Clear custom_prompt
    db_user.custom_prompt = None
    await session.commit()

    logger.info("personality.cleared", user_id=user_id)

    # Update message
    success_text = "🗑️ **Personality cleared**\n\n"
    success_text += "_Using default behavior now._"

    await callback.message.edit_text(success_text, parse_mode="Markdown")
    await callback.answer("Personality cleared")


@router.callback_query(F.data == "personality:cancel")
async def personality_cancel_callback(callback: types.CallbackQuery) -> None:
    """Handle 'Cancel' button.

    Closes the personality menu.

    Args:
        callback: Callback query from inline keyboard.
    """
    await callback.message.delete()
    await callback.answer()
