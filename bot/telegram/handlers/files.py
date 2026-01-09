"""Handlers for file uploads (Phase 1.5: Files API integration).

This module handles user file uploads (photos, documents) and
uploads them to Claude Files API for multimodal processing.

Flow:
1. User uploads file → Telegram
2. Bot downloads file from Telegram
3. Bot uploads to Files API → claude_file_id
4. Bot saves to user_files table
5. Bot creates message mention for context

NO __init__.py - use direct import:
    from telegram.handlers.files import router
"""

from datetime import datetime
from datetime import timedelta

from aiogram import F
from aiogram import Router
from aiogram import types
from config import FILES_API_TTL_HOURS
from core.files_api import upload_to_files_api
from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.repositories.message_repository import MessageRepository
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


@router.message(F.photo)
async def handle_photo(message: types.Message, session: AsyncSession) -> None:
    """Handle photo uploads with Files API integration.

    Downloads photo from Telegram, uploads to Files API,
    saves to database, and creates message mention.

    Args:
        message: Telegram message with photo.
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
                file_size=photo.file_size)

    # Check file size (Files API limit: 500MB)
    if photo.file_size and photo.file_size > 500 * 1024 * 1024:
        await message.answer("⚠️ File too large (max 500MB)")
        logger.warning("photo_handler.file_too_large",
                       user_id=user_id,
                       file_size=photo.file_size)
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

        # 3. Save to database
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
            expires_at=datetime.utcnow() + timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={
                "width": photo.width,
                "height": photo.height
            },
        )

        # 4. Create message with file mention
        await message_repo.create_message(
            chat_id=chat_id,
            message_id=message.message_id,
            thread_id=None,  # Will be set by context manager
            from_user_id=user_id,
            date=message.date.timestamp(),
            role="user",
            text_content=(f"📷 User uploaded: {filename} "
                          f"(image/jpeg, {format_size(len(photo_bytes))}) "
                          f"[Files API ID: {claude_file_id}]"),
        )

        await session.commit()

        logger.info("photo_handler.complete",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id)

        # Confirm upload
        await message.answer(
            f"✅ Photo uploaded successfully!\n\n"
            f"You can now ask me questions about this image.\n"
            f"File: `{filename}` ({format_size(len(photo_bytes))})",
            parse_mode="Markdown")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("photo_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer("❌ Failed to upload photo. Please try again later."
                            )


@router.message(F.document)
async def handle_document(message: types.Message,
                          session: AsyncSession) -> None:
    """Handle document uploads (PDFs, Office, code files).

    Downloads document from Telegram, uploads to Files API,
    saves to database, and creates message mention.

    Args:
        message: Telegram message with document.
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
                file_size=document.file_size)

    # Check file size (Files API limit: 500MB)
    if document.file_size and document.file_size > 500 * 1024 * 1024:
        await message.answer("⚠️ File too large (max 500MB)")
        logger.warning("document_handler.file_too_large",
                       user_id=user_id,
                       file_size=document.file_size)
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

        # 3. Save to database
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
            expires_at=datetime.utcnow() + timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={},
        )

        # 4. Create message with file mention
        await message_repo.create_message(
            chat_id=chat_id,
            message_id=message.message_id,
            thread_id=None,  # Will be set by context manager
            from_user_id=user_id,
            date=message.date.timestamp(),
            role="user",
            text_content=(
                f"{file_emoji} User uploaded: {document.file_name} "
                f"({document.mime_type}, {format_size(len(doc_bytes))}) "
                f"[Files API ID: {claude_file_id}]"),
        )

        await session.commit()

        logger.info("document_handler.complete",
                    user_id=user_id,
                    filename=document.file_name,
                    claude_file_id=claude_file_id)

        # Confirm upload
        await message.answer(
            f"✅ Document uploaded successfully!\n\n"
            f"You can now ask me questions about this file.\n"
            f"File: `{document.file_name}` ({format_size(len(doc_bytes))})",
            parse_mode="Markdown")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("document_handler.failed",
                     user_id=user_id,
                     filename=document.file_name,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to upload document. Please try again later.")
