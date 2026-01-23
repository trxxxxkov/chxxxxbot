"""Handler for /stop command.

This module handles the /stop command that stops active generation.

NO __init__.py - use direct import:
    from telegram.handlers.stop_generation import router
"""

from aiogram import Router
from aiogram import types
from aiogram.filters import Command
from telegram.generation_tracker import generation_tracker
from utils.structured_logging import get_logger

logger = get_logger(__name__)

router = Router(name="stop_generation")


@router.message(Command("stop"))
async def handle_stop_command(message: types.Message) -> None:
    """Handle /stop command to cancel active generation.

    Silently cancels generation - the [interrupted] indicator will be
    added to the partial message by the streaming handler.

    Args:
        message: Message with /stop command.
    """
    if not message.from_user or not message.chat:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Try to cancel active generation (silent - no reply messages)
    cancelled = await generation_tracker.cancel(chat_id, user_id)

    if cancelled:
        logger.info(
            "stop_generation.command_success",
            chat_id=chat_id,
            user_id=user_id,
        )
    else:
        logger.debug(
            "stop_generation.command_no_active",
            chat_id=chat_id,
            user_id=user_id,
        )


async def cancel_if_active(chat_id: int, user_id: int) -> bool:
    """Cancel active generation if any.

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.

    Returns:
        True if a generation was active and cancelled, False otherwise.
    """
    return await generation_tracker.cancel(chat_id, user_id)
