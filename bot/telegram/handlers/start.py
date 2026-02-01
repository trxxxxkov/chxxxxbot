"""Handlers for /start and /help commands.

This module contains handlers for basic bot commands that provide
information about bot functionality and available commands.
"""

from aiogram import Router
from aiogram import types
from aiogram.filters import Command
from db.repositories.user_repository import UserRepository
from i18n import get_lang
from i18n import get_text
from sqlalchemy.ext.asyncio import AsyncSession
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
async def help_handler(message: types.Message) -> None:
    """Handles /help command.

    Sends detailed help information about bot usage, available commands,
    and features to the user.

    Args:
        message: Incoming Telegram message with /help command.
    """
    logger.info(
        "help_command",
        user_id=message.from_user.id if message.from_user else None,
    )

    lang = get_lang(
        message.from_user.language_code if message.from_user else None)
    response_text = get_text("help.message", lang)
    await message.answer(response_text, parse_mode="Markdown")

    log_bot_response(
        "bot.help_response",
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        message_length=len(response_text),
    )
