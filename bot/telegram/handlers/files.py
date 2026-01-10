"""Handlers for file uploads (Phase 1.6: All file types support).

This module handles user file uploads (photos, documents, voice, audio, video)
and uploads them to Claude Files API for multimodal processing.

Flow for photos/documents:
1. User uploads file → Telegram
2. Bot downloads file from Telegram
3. Bot uploads to Files API → claude_file_id
4. Bot saves to user_files table
5. Bot creates message mention for context

Flow for voice messages (Phase 1.6):
1. User sends voice → Telegram
2. Bot downloads OGG file
3. Bot transcribes with OpenAI Whisper
4. Bot saves as TEXT message (not file!)
5. Claude handler processes as regular text

NO __init__.py - use direct import:
    from telegram.handlers.files import router
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from aiogram import F
from aiogram import Router
from aiogram import types
from config import FILES_API_TTL_HOURS
from core.claude.files_api import upload_to_files_api
from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_file_repository import UserFileRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="files")


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted size string (e.g., '1.5 MB').

    Examples:
        >>> format_size(1500000)
        '1.4 MB'
    """
    size: float = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_file_size_limit(user: types.User) -> int:
    """Get file size limit based on Telegram Premium status.

    Phase 1.6: Telegram imposes different file size limits for free
    and Premium users. This function returns the appropriate limit.

    Telegram limits:
    - Free users: 20 MB per file
    - Premium users: 2 GB per file

    Args:
        user: Telegram user object with is_premium attribute.

    Returns:
        Maximum file size in bytes.

    Examples:
        >>> user = types.User(id=123, is_bot=False, first_name="John",
        ...                   is_premium=False)
        >>> get_file_size_limit(user)
        20971520  # 20 MB

        >>> premium_user = types.User(id=456, is_bot=False, first_name="Jane",
        ...                          is_premium=True)
        >>> get_file_size_limit(premium_user)
        2147483648  # 2 GB
    """
    if user.is_premium:
        return 2 * 1024 * 1024 * 1024  # 2 GB
    return 20 * 1024 * 1024  # 20 MB


async def process_file_upload(message: types.Message,
                              session: AsyncSession) -> tuple[str, int]:
    """Upload file to Files API and save to database.

    Helper function for both photo and document uploads.
    Used when file is sent WITH caption (processed by claude handler).

    Args:
        message: Telegram message with photo or document.
        session: Database session.

    Returns:
        Tuple of (claude_file_id, thread_id).

    Raises:
        Exception: If upload fails.
    """
    if not message.from_user:
        raise ValueError("Message has no from_user")

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Determine file type
    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        file_size = photo.file_size
        file_type = FileType.IMAGE
        mime_type = "image/jpeg"
        filename = f"photo_{photo.file_id[:8]}.jpg"
        file_metadata = {"width": photo.width, "height": photo.height}
    elif message.document:
        document = message.document
        file_id = document.file_id
        file_unique_id = document.file_unique_id
        file_size = document.file_size
        mime_type = document.mime_type or "application/octet-stream"
        filename = document.file_name

        # Determine file type
        if mime_type == "application/pdf":
            file_type = FileType.PDF
        elif mime_type and mime_type.startswith("image/"):
            file_type = FileType.IMAGE
        else:
            file_type = FileType.DOCUMENT
        file_metadata = {}
    else:
        raise ValueError("Message has no photo or document")

    # Check file size (Telegram limits: 20MB free, 2GB Premium)
    if message.from_user:
        file_size_limit = get_file_size_limit(message.from_user)
        if file_size and file_size > file_size_limit:
            limit_str = "2 GB" if message.from_user.is_premium else "20 MB"
            raise ValueError(f"File too large (max {limit_str})")

    # Download from Telegram
    file_info = await message.bot.get_file(file_id)
    file_bytes_io = await message.bot.download_file(file_info.file_path)

    if not file_bytes_io:
        raise ValueError("Failed to download file from Telegram")

    file_bytes = file_bytes_io.read()

    logger.info("file_upload.download_complete",
                user_id=user_id,
                filename=filename,
                size_bytes=len(file_bytes))

    # Upload to Files API
    claude_file_id = await upload_to_files_api(file_bytes=file_bytes,
                                               filename=filename,
                                               mime_type=mime_type)

    logger.info("file_upload.files_api_complete",
                user_id=user_id,
                filename=filename,
                claude_file_id=claude_file_id)

    # Get or create thread
    chat_repo = ChatRepository(session)
    thread_repo = ThreadRepository(session)

    chat, _ = await chat_repo.get_or_create(telegram_id=chat_id,
                                            chat_type="private")

    telegram_thread_id = message.message_thread_id

    thread, _ = await thread_repo.get_or_create_thread(
        chat_id=chat_id, user_id=user_id, thread_id=telegram_thread_id)

    logger.info("file_upload.thread_resolved",
                thread_id=thread.id,
                telegram_thread_id=telegram_thread_id)

    # Save to database
    user_file_repo = UserFileRepository(session)

    await user_file_repo.create(
        message_id=message.message_id,
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        claude_file_id=claude_file_id,
        filename=filename,
        file_type=file_type,
        mime_type=mime_type,
        file_size=file_size or len(file_bytes),
        source=FileSource.USER,
        expires_at=datetime.now(timezone.utc) +
        timedelta(hours=FILES_API_TTL_HOURS),
        file_metadata=file_metadata,
    )

    logger.info("file_upload.complete",
                user_id=user_id,
                filename=filename,
                claude_file_id=claude_file_id,
                thread_id=thread.id)

    return claude_file_id, thread.id


@router.message(F.photo & ~F.caption)
async def handle_photo(message: types.Message, session: AsyncSession) -> None:
    """Handle photo uploads WITHOUT caption.

    If photo has caption, it will be processed by claude handler instead.

    Downloads photo from Telegram, uploads to Files API,
    saves to database, and creates message mention.

    Args:
        message: Telegram message with photo (no caption).
        session: Database session (injected by DatabaseMiddleware).
    """
    if not message.from_user or not message.photo:
        logger.warning("photo_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Get largest photo size
    photo = message.photo[-1]

    logger.info("photo_handler.received",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message.message_id,
                file_id=photo.file_id,
                file_size=photo.file_size,
                is_premium=message.from_user.is_premium)

    # Check file size (Telegram limits: 20MB free, 2GB Premium)
    file_size_limit = get_file_size_limit(message.from_user)
    if photo.file_size and photo.file_size > file_size_limit:
        limit_str = "2 GB" if message.from_user.is_premium else "20 MB"
        await message.answer(f"⚠️ File too large (max {limit_str})")
        logger.warning("photo_handler.file_too_large",
                       user_id=user_id,
                       file_size=photo.file_size,
                       limit=file_size_limit,
                       is_premium=message.from_user.is_premium)
        return

    try:
        # 1. Download from Telegram
        file_info = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file_info.file_path)

        if not file_bytes:
            await message.answer("⚠️ Failed to download photo from Telegram")
            logger.error("photo_handler.download_failed",
                         user_id=user_id,
                         file_id=photo.file_id)
            return

        # Read bytes
        photo_bytes = file_bytes.read()

        # Generate filename
        filename = f"photo_{photo.file_id[:8]}.jpg"

        logger.info("photo_handler.download_complete",
                    user_id=user_id,
                    filename=filename,
                    size_bytes=len(photo_bytes))

        # 2. Upload to Files API (BLOCKING - critical!)
        claude_file_id = await upload_to_files_api(file_bytes=photo_bytes,
                                                   filename=filename,
                                                   mime_type="image/jpeg")

        logger.info("photo_handler.files_api_upload_complete",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id)

        # 3. Get or create thread for this chat
        chat_repo = ChatRepository(session)
        thread_repo = ThreadRepository(session)

        # Get or create chat
        chat, _ = await chat_repo.get_or_create(telegram_id=chat_id,
                                                chat_type="private")

        # Get Telegram thread_id (for topics/forums)
        telegram_thread_id = message.message_thread_id

        # Get or create thread
        thread, _ = await thread_repo.get_or_create_thread(
            chat_id=chat_id, user_id=user_id, thread_id=telegram_thread_id)

        logger.info("photo_handler.thread_resolved",
                    thread_id=thread.id,
                    telegram_thread_id=telegram_thread_id)

        # 4. Save to database
        user_file_repo = UserFileRepository(session)
        message_repo = MessageRepository(session)

        await user_file_repo.create(
            message_id=message.message_id,
            telegram_file_id=photo.file_id,
            telegram_file_unique_id=photo.file_unique_id,
            claude_file_id=claude_file_id,
            filename=filename,
            file_type=FileType.IMAGE,
            mime_type="image/jpeg",
            file_size=photo.file_size or len(photo_bytes),
            source=FileSource.USER,
            expires_at=datetime.now(timezone.utc) +
            timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={
                "width": photo.width,
                "height": photo.height
            },
        )

        # 5. Create message with file mention
        # If user included caption, save it as question
        if message.caption:
            text_content = message.caption
            logger.info("photo_handler.caption_provided",
                        user_id=user_id,
                        caption_length=len(message.caption))
        else:
            # No caption - just file mention
            text_content = (f"📷 User uploaded: {filename} "
                            f"(image/jpeg, {format_size(len(photo_bytes))}) "
                            f"[Files API ID: {claude_file_id}]")

        await message_repo.create_message(
            chat_id=chat_id,
            message_id=message.message_id,
            thread_id=thread.id,
            from_user_id=user_id,
            date=message.date.timestamp(),
            role="user",
            text_content=text_content,
        )

        await session.commit()

        logger.info("photo_handler.complete",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id,
                    has_caption=bool(message.caption))

        # Don't send confirmation - let claude handler process the message
        # (caption will be processed automatically if present)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("photo_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer("❌ Failed to upload photo. Please try again later."
                            )


@router.message(F.document & ~F.caption)
async def handle_document(message: types.Message,
                          session: AsyncSession) -> None:
    """Handle document uploads WITHOUT caption.

    If document has caption, it will be processed by claude handler instead.

    Downloads document from Telegram, uploads to Files API,
    saves to database, and creates message mention.

    Args:
        message: Telegram message with document (no caption).
        session: Database session (injected by DatabaseMiddleware).
    """
    if not message.from_user or not message.document:
        logger.warning("document_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    document = message.document

    logger.info("document_handler.received",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message.message_id,
                filename=document.file_name,
                mime_type=document.mime_type,
                file_size=document.file_size,
                is_premium=message.from_user.is_premium)

    # Check file size (Telegram limits: 20MB free, 2GB Premium)
    file_size_limit = get_file_size_limit(message.from_user)
    if document.file_size and document.file_size > file_size_limit:
        limit_str = "2 GB" if message.from_user.is_premium else "20 MB"
        await message.answer(f"⚠️ File too large (max {limit_str})")
        logger.warning("document_handler.file_too_large",
                       user_id=user_id,
                       file_size=document.file_size,
                       limit=file_size_limit,
                       is_premium=message.from_user.is_premium)
        return

    # Determine file type
    if document.mime_type == "application/pdf":
        file_type = FileType.PDF
        file_emoji = "📄"
    elif document.mime_type and document.mime_type.startswith("image/"):
        file_type = FileType.IMAGE
        file_emoji = "🖼️"
    else:
        file_type = FileType.DOCUMENT
        file_emoji = "📎"

    try:
        # 1. Download from Telegram
        file_info = await message.bot.get_file(document.file_id)
        file_bytes = await message.bot.download_file(file_info.file_path)

        if not file_bytes:
            await message.answer("⚠️ Failed to download document from Telegram")
            logger.error("document_handler.download_failed",
                         user_id=user_id,
                         file_id=document.file_id)
            return

        # Read bytes
        doc_bytes = file_bytes.read()

        logger.info("document_handler.download_complete",
                    user_id=user_id,
                    filename=document.file_name,
                    size_bytes=len(doc_bytes))

        # 2. Upload to Files API
        claude_file_id = await upload_to_files_api(
            file_bytes=doc_bytes,
            filename=document.file_name,
            mime_type=document.mime_type or "application/octet-stream")

        logger.info("document_handler.files_api_upload_complete",
                    user_id=user_id,
                    filename=document.file_name,
                    claude_file_id=claude_file_id)

        # 3. Get or create thread for this chat
        chat_repo = ChatRepository(session)
        thread_repo = ThreadRepository(session)

        # Get or create chat
        chat, _ = await chat_repo.get_or_create(telegram_id=chat_id,
                                                chat_type="private")

        # Get Telegram thread_id (for topics/forums)
        telegram_thread_id = message.message_thread_id

        # Get or create thread
        thread, _ = await thread_repo.get_or_create_thread(
            chat_id=chat_id, user_id=user_id, thread_id=telegram_thread_id)

        logger.info("document_handler.thread_resolved",
                    thread_id=thread.id,
                    telegram_thread_id=telegram_thread_id)

        # 4. Save to database
        user_file_repo = UserFileRepository(session)
        message_repo = MessageRepository(session)

        await user_file_repo.create(
            message_id=message.message_id,
            telegram_file_id=document.file_id,
            telegram_file_unique_id=document.file_unique_id,
            claude_file_id=claude_file_id,
            filename=document.file_name,
            file_type=file_type,
            mime_type=document.mime_type or "application/octet-stream",
            file_size=document.file_size or len(doc_bytes),
            source=FileSource.USER,
            expires_at=datetime.now(timezone.utc) +
            timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={},
        )

        # 5. Create message with file mention
        # If user included caption, save it as question
        if message.caption:
            text_content = message.caption
            logger.info("document_handler.caption_provided",
                        user_id=user_id,
                        caption_length=len(message.caption))
        else:
            # No caption - just file mention
            text_content = (
                f"{file_emoji} User uploaded: {document.file_name} "
                f"({document.mime_type}, {format_size(len(doc_bytes))}) "
                f"[Files API ID: {claude_file_id}]")

        await message_repo.create_message(
            chat_id=chat_id,
            message_id=message.message_id,
            thread_id=thread.id,
            from_user_id=user_id,
            date=message.date.timestamp(),
            role="user",
            text_content=text_content,
        )

        await session.commit()

        logger.info("document_handler.complete",
                    user_id=user_id,
                    filename=document.file_name,
                    claude_file_id=claude_file_id,
                    has_caption=bool(message.caption))

        # Don't send confirmation - let claude handler process the message
        # (caption will be processed automatically if present)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("document_handler.failed",
                     user_id=user_id,
                     filename=document.file_name,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to upload document. Please try again later.")


# Voice/Audio/Video handlers moved to media_handlers.py (Phase 1.6)
# Universal media architecture with MediaProcessor
