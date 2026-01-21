"""Batch processor for unified pipeline.

This module processes batches of ProcessedMessage objects and delegates
to the Claude handler for actual processing.

The processor:
1. Saves files to database (they're already uploaded to Files API)
2. Calls the Claude handler processing logic

NO __init__.py - use direct import:
    from telegram.pipeline.processor import process_batch
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from cache.thread_cache import invalidate_files
from config import FILES_API_TTL_HOURS
from db.engine import get_session
from db.models.user_file import FileSource
from db.models.user_file import FileType as DbFileType
from db.repositories.user_file_repository import UserFileRepository
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import ProcessedMessage
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def _media_type_to_file_type(media_type: MediaType) -> DbFileType:
    """Convert MediaType to database FileType.

    Args:
        media_type: Pipeline MediaType.

    Returns:
        Database FileType.
    """
    mapping = {
        MediaType.VOICE: DbFileType.VOICE,
        MediaType.VIDEO_NOTE: DbFileType.VIDEO,
        MediaType.AUDIO: DbFileType.AUDIO,
        MediaType.VIDEO: DbFileType.VIDEO,
        MediaType.IMAGE: DbFileType.IMAGE,
        MediaType.PDF: DbFileType.PDF,
        MediaType.DOCUMENT: DbFileType.DOCUMENT,
    }
    return mapping.get(media_type, DbFileType.DOCUMENT)


async def process_batch(
    thread_id: int,
    messages: list[ProcessedMessage],
) -> None:
    """Process a batch of ProcessedMessage objects.

    This function:
    1. Saves files to database (they're already uploaded to Files API)
    2. Calls the Claude handler processing logic

    Args:
        thread_id: Database thread ID.
        messages: List of ProcessedMessage objects.
    """
    if not messages:
        logger.warning("processor.empty_batch", thread_id=thread_id)
        return

    logger.info(
        "processor.batch_start",
        thread_id=thread_id,
        batch_size=len(messages),
    )

    try:
        # Create session for file saving
        async with get_session() as session:
            # Save files to database (they're already uploaded to Files API)
            file_repo = UserFileRepository(session)

            for processed in messages:
                if processed.files:
                    for file in processed.files:
                        await file_repo.create(
                            message_id=processed.metadata.message_id,
                            telegram_file_id=file.telegram_file_id,
                            telegram_file_unique_id=file.
                            telegram_file_unique_id,
                            claude_file_id=file.claude_file_id,
                            filename=file.filename,
                            file_type=_media_type_to_file_type(file.file_type),
                            mime_type=file.mime_type,
                            file_size=file.size_bytes,
                            source=FileSource.USER,
                            expires_at=datetime.now(timezone.utc) +
                            timedelta(hours=FILES_API_TTL_HOURS),
                            file_metadata=file.metadata,
                        )

                        logger.info(
                            "processor.file_saved",
                            thread_id=thread_id,
                            message_id=processed.metadata.message_id,
                            claude_file_id=file.claude_file_id,
                            filename=file.filename,
                        )

            await session.commit()

            # Invalidate files cache if any files were uploaded
            files_uploaded = any(p.files for p in messages)
            if files_uploaded:
                await invalidate_files(thread_id)

        # Call Claude handler directly with ProcessedMessage list
        # Import here to avoid circular dependency
        from telegram.handlers.claude import \
            _process_message_batch  # pylint: disable=import-outside-toplevel

        await _process_message_batch(thread_id, messages)

        logger.info(
            "processor.batch_complete",
            thread_id=thread_id,
            batch_size=len(messages),
        )

    except Exception as e:
        logger.error(
            "processor.batch_failed",
            thread_id=thread_id,
            batch_size=len(messages),
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise
