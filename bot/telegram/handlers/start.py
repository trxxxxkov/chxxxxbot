"""Handlers for /start and /help commands.

This module contains handlers for basic bot commands that provide
information about bot functionality and available commands.
"""

from aiogram import Router
from aiogram import types
from aiogram.filters import Command
import config
from db.repositories.user_repository import UserRepository
from i18n import get_lang
from i18n import get_text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.handlers.admin import is_privileged
from utils.bot_response import log_bot_response
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="start")


@router.message(Command("start"))
async def start_handler(message: types.Message, session: AsyncSession) -> None:
    """Handles /start command.

    Creates or updates user in database and sends welcome message.
    Shows "Welcome!" for new users and "Welcome back!" for returning users.

    Args:
        message: Incoming Telegram message with /start command.
        session: Database session injected by DatabaseMiddleware.
    """
    if not message.from_user:
        await message.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user = message.from_user
    lang = get_lang(user.language_code)
    user_repo = UserRepository(session)

    # Get or create user in database
    _, was_created = await user_repo.get_or_create(
        telegram_id=user.id,
        is_bot=user.is_bot,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=user.is_premium or False,
        added_to_attachment_menu=user.added_to_attachment_menu or False,
        allows_users_to_create_topics=(user.allows_users_to_create_topics or
                                       False),
    )

    logger.info(
        "start_command",
        user_id=user.id,
        username=user.username,
        was_created=was_created,
    )

    # Note: user.new_user_joined is logged in UserRepository.get_or_create()

    # Different message for new vs returning users
    greeting_key = "start.welcome_new" if was_created else "start.welcome_back"
    greeting = get_text(greeting_key, lang)

    response_text = get_text("start.message", lang, greeting=greeting)
    await message.answer(response_text)

    log_bot_response(
        "bot.start_response",
        chat_id=message.chat.id,
        user_id=user.id,
        message_length=len(response_text),
        was_new_user=was_created,
    )


@router.message(Command("help"))
async def help_handler(
    message: types.Message,
    session: AsyncSession,
) -> None:
    """Handles /help command.

    Builds dynamic help text based on user's privilege level.
    Regular users see basic, model, and payment commands.
    Privileged users also see admin commands.

    Args:
        message: Incoming Telegram message with /help command.
        session: Database session from middleware.
    """
    user_id = message.from_user.id if message.from_user else None
    logger.info("help_command", user_id=user_id)

    lang = get_lang(
        message.from_user.language_code if message.from_user else None)

    show_admin = user_id is not None and is_privileged(user_id)

    # Build help text
    parts = [get_text("help.header", lang)]

    # Basic commands
    parts.append(get_text("help.section_basic", lang))
    parts.append(get_text("help.cmd_start", lang))
    parts.append(get_text("help.cmd_help", lang))
    parts.append(get_text("help.cmd_stop", lang))
    parts.append(get_text("help.cmd_clear", lang))

    # Model & Settings
    parts.append(get_text("help.section_model", lang))
    parts.append(get_text("help.cmd_model", lang))
    parts.append(get_text("help.cmd_personality", lang))

    # Payment
    parts.append(get_text("help.section_payment", lang))
    parts.append(get_text("help.cmd_pay", lang))
    parts.append(get_text("help.cmd_balance", lang))
    parts.append(get_text("help.cmd_refund", lang))

    # Admin (only for privileged users)
    if show_admin:
        parts.append(get_text("help.section_admin", lang))
        parts.append(get_text("help.cmd_topup", lang))
        parts.append(get_text("help.cmd_set_margin", lang))
        parts.append(get_text("help.cmd_announce", lang))

    # Contact — first privileged user's username
    contact_username = await _get_contact_username(session)
    if contact_username:
        parts.append(get_text("help.contact", lang, username=contact_username))

    response_text = "".join(parts)
    await message.answer(response_text, parse_mode="HTML")

    log_bot_response(
        "bot.help_response",
        chat_id=message.chat.id,
        user_id=user_id,
        message_length=len(response_text),
    )


async def _get_contact_username(session: AsyncSession) -> str | None:
    """Get username of the first privileged user for contact info.

    Args:
        session: Database session.

    Returns:
        Username string or None if not available.
    """
    if not config.PRIVILEGED_USERS:
        return None

    first_id = min(config.PRIVILEGED_USERS)
    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(first_id)
    if user and user.username:
        return user.username
    return None
