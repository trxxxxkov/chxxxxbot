"""Handlers for /start and /help commands.

This module contains handlers for basic bot commands that provide
information about bot functionality and available commands.
"""

from aiogram import Router
from aiogram import types
from aiogram.filters import Command
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
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
        await message.answer("⚠️ Unable to identify user.")
        return

    user = message.from_user
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

    # Dashboard tracking event for new users
    if was_created:
        logger.info("user.new_user_joined",
                    user_id=user.id,
                    username=user.username)

    # Different message for new vs returning users
    greeting = "👋 Welcome!" if was_created else "👋 Welcome back!"

    await message.answer(f"{greeting} I'm an LLM bot.\n\n"
                         "Available commands:\n"
                         "/start - Show this message\n"
                         "/help - Get help\n\n"
                         "Send me any message and I'll echo it back!")


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

    await message.answer(
        "🤖 *Help*\n\n"
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n\n"
        "*Usage:*\n"
        "Just send me any text message and I'll echo it back.\n\n"
        "This is a minimal bot implementation. "
        "LLM integration coming soon!",
        parse_mode="Markdown")
