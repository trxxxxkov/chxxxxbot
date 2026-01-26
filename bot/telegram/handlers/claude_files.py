"""File handling utilities for Claude handler.

This module provides file processing and delivery functions for generated
content from tool executions.

NO __init__.py - use direct import:
    from telegram.handlers.claude_files import process_generated_files
"""

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

from aiogram import types
from cache.thread_cache import invalidate_files
from config import FILES_API_TTL_HOURS
from core.claude.files_api import upload_to_files_api
from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.repositories.user_file_repository import UserFileRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


async def _process_single_file(
    file_data: Dict[str, Any],
    first_message: types.Message,
    thread_id: int,
    user_file_repo: UserFileRepository,
    chat_id: int,
    user_id: int,
    telegram_thread_id: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Process a single file: upload, send, save.

    Args:
        file_data: Dict with filename, content, mime_type.
        first_message: First message in batch (for bot reference).
        thread_id: Internal thread ID.
        user_file_repo: UserFile repository.
        chat_id: Telegram chat ID.
        user_id: User ID for logging.
        telegram_thread_id: Telegram thread ID (for forums).

    Returns:
        Dict with file info on success, None on failure.
    """
    try:
        filename = file_data["filename"]
        file_bytes = file_data["content"]
        mime_type = file_data["mime_type"]
        # Context helps model understand what this file is about
        upload_context = file_data.get("context")

        # Step 1: Upload to Files API (parallel with other files)
        claude_file_id = await upload_to_files_api(
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        # Determine file type from MIME
        if mime_type.startswith("image/"):
            file_type = FileType.IMAGE
        elif mime_type == "application/pdf":
            file_type = FileType.PDF
        elif mime_type.startswith("audio/"):
            file_type = FileType.AUDIO
        elif mime_type.startswith("video/"):
            file_type = FileType.VIDEO
        else:
            file_type = FileType.DOCUMENT

        # Step 2: Send to Telegram
        telegram_file_id = None
        telegram_file_unique_id = None

        if file_type == FileType.IMAGE and mime_type in [
                "image/jpeg", "image/png", "image/gif", "image/webp"
        ]:
            sent_msg = await first_message.bot.send_photo(
                chat_id=chat_id,
                photo=types.BufferedInputFile(file_bytes, filename=filename),
                message_thread_id=telegram_thread_id,
            )
            if sent_msg.photo:
                largest = max(sent_msg.photo, key=lambda p: p.file_size or 0)
                telegram_file_id = largest.file_id
                telegram_file_unique_id = largest.file_unique_id
        else:
            sent_msg = await first_message.bot.send_document(
                chat_id=chat_id,
                document=types.BufferedInputFile(file_bytes, filename=filename),
                message_thread_id=telegram_thread_id,
            )
            if sent_msg.document:
                telegram_file_id = sent_msg.document.file_id
                telegram_file_unique_id = sent_msg.document.file_unique_id

        # Step 3: Save to database
        await user_file_repo.create(
            message_id=first_message.message_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            claude_file_id=claude_file_id,
            filename=filename,
            file_type=file_type,
            mime_type=mime_type,
            file_size=len(file_bytes),
            source=FileSource.ASSISTANT,
            expires_at=datetime.now(timezone.utc) +
            timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={},
            upload_context=upload_context,
        )

        # Dashboard tracking event
        logger.info(
            "files.bot_file_sent",
            user_id=user_id,
            file_type=file_type.value,
            filename=filename,
        )

        return {
            "filename": filename,
            "claude_file_id": claude_file_id,
            "file_type": file_type.value,
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            "stream.file_delivery_failed",
            filename=file_data.get("filename"),
            error=str(e),
            exc_info=True,
        )
        return None


async def process_generated_files(
    result: dict,
    first_message: types.Message,
    thread_id: int,
    _session: AsyncSession,
    user_file_repo: UserFileRepository,
    chat_id: int,
    user_id: int,
    telegram_thread_id: int | None,
) -> None:
    """Process and deliver files generated by tools.

    Handles the _file_contents pattern: extracts files from tool results,
    uploads to Files API, sends to Telegram, and saves to database.

    Files are processed in PARALLEL for better performance.

    Args:
        result: Tool result dict containing _file_contents.
        first_message: First message in batch (for bot reference).
        thread_id: Internal thread ID.
        _session: Database session.
        user_file_repo: UserFile repository.
        chat_id: Telegram chat ID.
        user_id: User ID for logging.
        telegram_thread_id: Telegram thread ID (for forums).
    """
    file_contents = result.pop("_file_contents")

    if not file_contents:
        return

    # Process all files in parallel
    logger.info(
        "files.parallel_processing_start",
        file_count=len(file_contents),
        filenames=[f.get("filename") for f in file_contents],
    )

    tasks = [
        _process_single_file(
            file_data=file_data,
            first_message=first_message,
            thread_id=thread_id,
            user_file_repo=user_file_repo,
            chat_id=chat_id,
            user_id=user_id,
            telegram_thread_id=telegram_thread_id,
        ) for file_data in file_contents
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect successful deliveries
    delivered_files: List[Dict[str, Any]] = []
    for i, file_result in enumerate(results):
        if isinstance(file_result, BaseException):
            logger.error(
                "files.parallel_processing_exception",
                filename=file_contents[i].get("filename"),
                error=str(file_result),
            )
        elif file_result is not None:
            delivered_files.append(file_result)

    logger.info(
        "files.parallel_processing_complete",
        total=len(file_contents),
        successful=len(delivered_files),
    )

    if delivered_files:
        # Invalidate files cache so next request sees new files
        await invalidate_files(thread_id)

        # Format result with claude_file_id so Claude can reference files
        file_list = "\n".join(f"- {f['filename']} ({f['file_type']}): "
                              f"claude_file_id={f['claude_file_id']}"
                              for f in delivered_files)
        result["files_delivered"] = (
            f"Successfully sent {len(delivered_files)} file(s) to user:\n"
            f"{file_list}\n\n"
            f"Use these claude_file_id values with analyze_image or "
            f"analyze_pdf tools if you need to analyze the files.")
