"""Personality (custom prompt) keyboard for /personality command.

This module creates inline keyboards for viewing and editing user's
custom_prompt (Phase 1.4.2: 3-level system prompt architecture).

NO __init__.py - use direct import:
    from telegram.keyboards.personality_selector import get_personality_keyboard
"""

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from i18n import get_text


def get_personality_keyboard(has_custom_prompt: bool,
                             lang: str = "en") -> InlineKeyboardBuilder:
    """Build inline keyboard for personality management.

    Creates keyboard with options:
    - View current (if exists)
    - Edit/Set new
    - Clear (if exists)
    - Cancel

    Args:
        has_custom_prompt: Whether user has custom_prompt set.
        lang: Language code ('en' or 'ru').

    Returns:
        InlineKeyboardBuilder with personality management buttons.

    Examples:
        >>> keyboard = get_personality_keyboard(has_custom_prompt=True)
        >>> keyboard.as_markup()
        # Returns InlineKeyboardMarkup with buttons
    """
    builder = InlineKeyboardBuilder()

    # View current (only if exists)
    if has_custom_prompt:
        builder.row(
            InlineKeyboardButton(text=get_text("personality.btn_view", lang),
                                 callback_data="personality:view"))

    # Edit/Set new
    button_key = "personality.btn_edit" if has_custom_prompt else "personality.btn_set_new"
    builder.row(
        InlineKeyboardButton(text=get_text(button_key, lang),
                             callback_data="personality:edit"))

    # Clear (only if exists)
    if has_custom_prompt:
        builder.row(
            InlineKeyboardButton(text=get_text("personality.btn_clear", lang),
                                 callback_data="personality:clear"))

    # Cancel (always)
    builder.row(
        InlineKeyboardButton(text=get_text("personality.btn_cancel", lang),
                             callback_data="personality:cancel"))

    return builder


def format_personality_info(custom_prompt: str | None,
                            truncate: int = 500,
                            lang: str = "en") -> str:
    r"""Format custom prompt for display.

    Args:
        custom_prompt: User's custom prompt (or None).
        truncate: Maximum length before truncating. Defaults to 500.
        lang: Language code ('en' or 'ru').

    Returns:
        Formatted string with custom prompt or "Not set" message.

    Examples:
        >>> format_personality_info("You are a helpful assistant")
        '```\nYou are a helpful assistant\n```'

        >>> format_personality_info(None)
        '_No personality set. Using default behavior._'
    """
    if not custom_prompt:
        return get_text("personality.not_set", lang)

    # Truncate if too long
    display_text = custom_prompt
    if len(display_text) > truncate:
        display_text = display_text[:truncate] + "..."

    # Format in code block for better readability
    return f"```\n{display_text}\n```"
