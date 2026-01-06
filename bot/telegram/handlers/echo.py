"""Echo handler for all regular messages"""

from aiogram import Router, types, F

from utils.logging import get_logger

logger = get_logger(__name__)
router = Router(name="echo")


@router.message(F.text)
async def echo_handler(message: types.Message) -> None:
    """Echo back user's text message"""
    logger.info(
        "echo_message",
        user_id=message.from_user.id if message.from_user else None,
        text_length=len(message.text) if message.text else 0,
    )

    await message.answer(f"You said: {message.text}")
