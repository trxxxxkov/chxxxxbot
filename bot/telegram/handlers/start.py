"""Handlers for /start and /help commands.

This module contains handlers for basic bot commands that provide
information about bot functionality and available commands.
"""

from aiogram import Router
from aiogram import types
from aiogram.filters import Command
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="start")


@router.message(Command("start"))
async def start_handler(message: types.Message) -> None:
    """Handles /start command.

    Sends a welcome message to the user with basic information about
    available bot commands and functionality.

    Args:
        message: Incoming Telegram message with /start command.
    """
    logger.info(
        "start_command",
        user_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None,
    )

    await message.answer("👋 Welcome! I'm an LLM bot.\n\n"
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
