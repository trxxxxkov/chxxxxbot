"""Edited message handler.

Handles Telegram edited_message updates to track message edits in database.
Stores original content and edit count for context.

NO __init__.py - use direct import:
    from telegram.handlers.edited_message import router
"""

from aiogram import Router
from aiogram import types
from db.repositories.message_repository import MessageRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Create router for edited messages
router = Router(name="edited_message")


@router.edited_message()
async def handle_edited_message(
    message: types.Message,
    session: AsyncSession,
) -> None:
    """Handle edited message updates.

    Updates message content in database, tracks edit count, and saves
    original content on first edit.

    Args:
        message: Edited Telegram message.
        session: Database session from middleware.
    """
    chat_id = message.chat.id
    message_id = message.message_id

    logger.info(
        "edited_message.received",
        chat_id=chat_id,
        message_id=message_id,
        user_id=message.from_user.id if message.from_user else None,
    )

    msg_repo = MessageRepository(session)

    # Get new text content
    text_content = message.text if message.text else None
    caption = message.caption if message.caption else None
    # edit_date can be datetime or int depending on aiogram version/context
    edit_date = None
    if message.edit_date:
        if hasattr(message.edit_date, 'timestamp'):
            edit_date = int(message.edit_date.timestamp())
        else:
            edit_date = int(message.edit_date)

    # Update message in database
    updated_msg = await msg_repo.update_message_edit(
        chat_id=chat_id,
        message_id=message_id,
        text_content=text_content,
        caption=caption,
        edit_date=edit_date,
    )

    if updated_msg:
        logger.info(
            "edited_message.updated",
            chat_id=chat_id,
            message_id=message_id,
            edit_count=updated_msg.edit_count,
            has_original=updated_msg.original_content is not None,
        )
    else:
        # Message not in database (might be old or from before bot started)
        logger.debug(
            "edited_message.not_found",
            chat_id=chat_id,
            message_id=message_id,
        )
