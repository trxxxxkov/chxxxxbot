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
from i18n import get_lang
from i18n import get_text
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
        await message.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user_id = message.from_user.id
    lang = get_lang(message.from_user.language_code)

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
            added_to_attachment_menu=(message.from_user.added_to_attachment_menu
                                      or False),
        )
        await session.commit()

    # Format message
    message_text = get_text("personality.title", lang)
    message_text += get_text("personality.description", lang)
    message_text += get_text("personality.current", lang)
    message_text += format_personality_info(db_user.custom_prompt, lang=lang)

    # Send keyboard
    keyboard = get_personality_keyboard(has_custom_prompt=db_user.custom_prompt
                                        is not None,
                                        lang=lang)

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
        await callback.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user_id = callback.from_user.id
    lang = get_lang(callback.from_user.language_code)

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user or not db_user.custom_prompt:
        await callback.answer(get_text("personality.no_personality_set", lang))
        return

    # Show full text (no truncation)
    view_text = get_text("personality.view_title", lang)
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
        await callback.answer(get_text("common.unable_to_identify_user", "en"))
        return

    lang = get_lang(callback.from_user.language_code)

    # Enter waiting state
    await state.set_state(PersonalityStates.waiting_for_text)

    # Save user_id in state data
    await state.update_data(user_id=callback.from_user.id)

    logger.info("personality.edit_started", user_id=callback.from_user.id)

    await callback.message.answer(get_text("personality.edit_prompt", lang))
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
    lang = get_lang(
        message.from_user.language_code if message.from_user else None)

    if not message.text or not message.from_user:
        await message.answer(get_text("common.send_text_message", lang))
        return

    user_id = message.from_user.id
    new_prompt = message.text.strip()

    # Validate length (optional, but good practice)
    if len(new_prompt) < 10:
        await message.answer(get_text("personality.text_too_short", lang))
        return

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user:
        await message.answer(get_text("common.user_not_found", lang))
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
    success_text = get_text("personality.updated", lang)
    success_text += get_text("personality.your_new", lang)
    success_text += format_personality_info(new_prompt, truncate=300, lang=lang)

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
        await callback.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user_id = callback.from_user.id
    lang = get_lang(callback.from_user.language_code)

    # Get user
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_telegram_id(user_id)

    if not db_user:
        await callback.answer(get_text("common.user_not_found", lang))
        return

    # Clear custom_prompt
    db_user.custom_prompt = None
    await session.commit()

    logger.info("personality.cleared", user_id=user_id)

    # Update message
    await callback.message.edit_text(get_text("personality.cleared", lang),
                                     parse_mode="Markdown")
    await callback.answer(get_text("personality.cleared_toast", lang))


@router.callback_query(F.data == "personality:cancel")
async def personality_cancel_callback(callback: types.CallbackQuery) -> None:
    """Handle 'Cancel' button.

    Closes the personality menu.

    Args:
        callback: Callback query from inline keyboard.
    """
    await callback.message.delete()
    await callback.answer()
