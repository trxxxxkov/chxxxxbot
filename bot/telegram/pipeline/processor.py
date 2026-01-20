"""Batch processor for unified pipeline.

This module processes batches of ProcessedMessage objects by bridging
to the existing Claude handler logic. This allows gradual migration
while maintaining compatibility.

The processor:
1. Converts ProcessedMessage to the format expected by existing code
2. Calls the existing _process_message_batch logic
3. Handles saving files to database

Future: This will be refactored to directly process ProcessedMessage
without the bridge.

NO __init__.py - use direct import:
    from telegram.pipeline.processor import process_batch
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Optional

from aiogram import types
from config import FILES_API_TTL_HOURS
from db.engine import get_session
from db.models.user_file import FileSource
from db.models.user_file import FileType as DbFileType
from db.repositories.user_file_repository import UserFileRepository
from telegram.media_processor import MediaContent
from telegram.media_processor import MediaType as OldMediaType
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import ProcessedMessage
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def _media_type_to_old(media_type: MediaType) -> OldMediaType:
    """Convert new MediaType to old MediaType enum.

    Args:
        media_type: New MediaType.

    Returns:
        Old MediaType.
    """
    mapping = {
        MediaType.VOICE: OldMediaType.VOICE,
        MediaType.VIDEO_NOTE: OldMediaType.VIDEO_NOTE,
        MediaType.AUDIO: OldMediaType.AUDIO,
        MediaType.VIDEO: OldMediaType.VIDEO,
        MediaType.IMAGE: OldMediaType.IMAGE,
        MediaType.DOCUMENT: OldMediaType.DOCUMENT,
        MediaType.PDF: OldMediaType.DOCUMENT,
    }
    return mapping.get(media_type, OldMediaType.DOCUMENT)


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


def _convert_to_media_content(
    processed: ProcessedMessage,) -> Optional[MediaContent]:
    """Convert ProcessedMessage to legacy MediaContent format.

    This is a bridge function to support the existing Claude handler.

    Args:
        processed: ProcessedMessage from new pipeline.

    Returns:
        MediaContent for old pipeline, or None.
    """
    # Check for transcript (voice/video_note)
    if processed.transcript:
        # Determine media type from original message
        if processed.original_message.voice:
            media_type = OldMediaType.VOICE
            duration = processed.original_message.voice.duration
        elif processed.original_message.video_note:
            media_type = OldMediaType.VIDEO
            duration = processed.original_message.video_note.duration
        else:
            media_type = OldMediaType.VOICE
            duration = int(processed.transcript.duration_seconds)

        return MediaContent(
            type=media_type,
            text_content=processed.transcript.text,
            file_id=None,
            metadata={
                "duration": duration,
                "cost_usd": processed.transcript.cost_usd,
                "language": processed.transcript.detected_language,
            },
        )

    # Check for files
    if processed.files:
        # Use first file (most messages have single file)
        file = processed.files[0]
        media_type = _media_type_to_old(file.file_type)

        return MediaContent(
            type=media_type,
            text_content=None,
            file_id=file.claude_file_id,
            metadata={
                "filename": file.filename,
                "size_bytes": file.size_bytes,
                "mime_type": file.mime_type,
                **file.metadata,
            },
        )

    return None


async def process_batch(
    thread_id: int,
    messages: list[ProcessedMessage],
) -> None:
    """Process a batch of ProcessedMessage objects.

    This function bridges between the new unified pipeline and the
    existing Claude handler. It:
    1. Saves files to database (they're already uploaded to Files API)
    2. Converts ProcessedMessage to legacy format
    3. Calls the existing processing logic

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

        # Convert to legacy format for existing handler
        legacy_messages: list[tuple[types.Message, Optional[MediaContent]]] = []

        for processed in messages:
            media_content = _convert_to_media_content(processed)
            legacy_messages.append((processed.original_message, media_content))

        # Call existing processing logic
        # Import here to avoid circular dependency
        from telegram.handlers.claude import \
            _process_message_batch  # pylint: disable=import-outside-toplevel

        await _process_message_batch(thread_id, legacy_messages)

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
