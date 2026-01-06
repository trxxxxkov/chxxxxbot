"""Echo handler for all regular messages.

This module contains a catch-all handler that echoes back any text message
sent by the user. It serves as a fallback handler for messages that don't
match any specific command handlers.
"""

from aiogram import Router, types, F

from utils.logging import get_logger

logger = get_logger(__name__)
router = Router(name="echo")


@router.message(F.text)
async def echo_handler(message: types.Message) -> None:
    """Handles all text messages by echoing them back.

    This is a catch-all handler that responds to any text message that
    doesn't match more specific handlers. It logs the message and sends
    back the same text prefixed with "You said: ".

    Args:
        message: Incoming Telegram message with text content.
    """
    logger.info(
        "echo_message",
        user_id=message.from_user.id if message.from_user else None,
        text_length=len(message.text) if message.text else 0,
    )

    await message.answer(f"You said: {message.text}")
