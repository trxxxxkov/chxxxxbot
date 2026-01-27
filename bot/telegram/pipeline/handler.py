"""Unified message handler for the new pipeline.

This module provides a single handler for all message types, replacing:
- telegram/handlers/files.py (photo, document handlers)
- telegram/handlers/media_handlers.py (voice, audio, video, video_note)
- telegram/handlers/claude.py (text handler only)

All processing (download, upload, transcription) happens in the normalizer
BEFORE messages enter the queue, eliminating race conditions.

NO __init__.py - use direct import:
    from telegram.pipeline.handler import router
"""

import time

from aiogram import F
from aiogram import Router
from aiogram import types
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.generation_tracker import generation_tracker
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import TranscriptInfo
from telegram.pipeline.normalizer import get_normalizer
from telegram.pipeline.queue import ProcessedMessageQueue
from telegram.pipeline.tracker import get_media_group_tracker
from telegram.pipeline.tracker import get_tracker
from telegram.thread_resolver import get_or_create_thread
from utils.metrics import record_message_received
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Router for unified pipeline
router = Router(name="unified_pipeline")

# Queue instance (initialized on first use)
_queue: ProcessedMessageQueue | None = None


async def _process_batch(thread_id: int,
                         messages: list[ProcessedMessage]) -> None:
    """Process a batch of messages.

    This callback is called by the queue when a batch is ready.
    It delegates to the ClaudeProcessor for actual processing.

    Args:
        thread_id: Database thread ID.
        messages: List of ProcessedMessage objects.
    """
    # Import here to avoid circular dependency
    from telegram.pipeline.processor import \
        process_batch  # pylint: disable=import-outside-toplevel

    await process_batch(thread_id, messages)


def get_queue() -> ProcessedMessageQueue:
    """Get or create the global queue instance.

    Returns:
        ProcessedMessageQueue singleton.
    """
    global _queue  # pylint: disable=global-statement
    if _queue is None:
        _queue = ProcessedMessageQueue(_process_batch)
        logger.info("unified_handler.queue_initialized")
    return _queue


@router.message(F.text | F.caption | F.photo | F.document | F.voice | F.audio |
                F.video | F.video_note)
async def handle_message(message: types.Message, session: AsyncSession) -> None:
    """Unified handler for all message types.

    This single handler processes:
    - Text messages
    - Photos (with or without caption)
    - Documents (PDFs, images, etc.)
    - Voice messages (auto-transcribed)
    - Audio files
    - Video files
    - Video notes (round videos, auto-transcribed)

    Flow:
    1. Normalize message (download, upload, transcribe)
    2. Get or create thread
    3. Add to queue

    Args:
        message: Telegram message.
        session: Database session from middleware.
    """
    if not message.from_user:
        logger.warning(
            "unified_handler.no_user",
            message_id=message.message_id,
        )
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id

    # Phase 2.5: Cancel any active generation for this user in same thread
    # New message will be queued and processed after current generation stops
    if generation_tracker.is_active(chat_id, user_id, thread_id):
        await generation_tracker.cancel(chat_id, user_id, thread_id)
        logger.info(
            "unified_handler.cancelled_active_generation",
            user_id=user_id,
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=message.message_id,
        )

    # Determine content type for metrics
    content_type = _get_content_type(message)

    logger.info(
        "unified_handler.received",
        user_id=user_id,
        chat_id=chat_id,
        message_id=message.message_id,
        content_type=content_type,
    )

    # Record metrics
    record_message_received(chat_type=message.chat.type,
                            content_type=content_type)

    # Track this message for batch synchronization
    # This allows the queue to wait for all messages in a chat
    # before processing (e.g., forwarded text + photo arrive separately)
    tracker = get_tracker()
    await tracker.start(chat_id, message.message_id)

    # Track media group if present (for smart waiting)
    media_group_id = getattr(message, 'media_group_id', None)
    if media_group_id:
        media_group_tracker = get_media_group_tracker()
        await media_group_tracker.register(str(media_group_id))

    handler_start = time.perf_counter()
    normalization_finished = False

    try:
        # 1. Normalize message (all I/O happens here)
        normalize_start = time.perf_counter()
        normalizer = get_normalizer()
        processed = await normalizer.normalize(message)
        normalize_ms = (time.perf_counter() - normalize_start) * 1000

        logger.info(
            "unified_handler.normalized",
            user_id=user_id,
            message_id=message.message_id,
            has_text=bool(processed.text),
            has_files=processed.has_files,
            has_transcript=processed.has_transcript,
            normalize_ms=round(normalize_ms, 2),
        )

        # 2. Charge for transcription if applicable
        if processed.transcript and not processed.transcription_charged:
            await _charge_transcription(
                session=session,
                user_id=user_id,
                message_id=message.message_id,
                transcript=processed.transcript,
                content_type=content_type,
            )
            # Mark as charged to avoid double charging
            object.__setattr__(processed, 'transcription_charged', True)

        # 3. Get or create thread
        thread_start = time.perf_counter()
        thread = await get_or_create_thread(message, session)
        await session.commit()
        thread_resolve_ms = (time.perf_counter() - thread_start) * 1000

        logger.info(
            "unified_handler.thread_resolved",
            user_id=user_id,
            thread_id=thread.id,
            thread_resolve_ms=round(thread_resolve_ms, 2),
        )

        # 4. Mark normalization complete BEFORE adding to queue
        # This must happen before queue.add() because add() waits for
        # pending normalizations. If we wait until finally block, we get
        # deadlock: all messages wait for each other's finish().
        await tracker.finish(chat_id, message.message_id)
        normalization_finished = True

        # 5. Add to queue
        queue = get_queue()
        await queue.add(thread_id=thread.id, message=processed)

        handler_ms = (time.perf_counter() - handler_start) * 1000
        logger.info(
            "unified_handler.queued",
            user_id=user_id,
            thread_id=thread.id,
            content_type=content_type,
            normalize_ms=round(normalize_ms, 2),
            thread_resolve_ms=round(thread_resolve_ms, 2),
            total_handler_ms=round(handler_ms, 2),
        )

        # Dashboard tracking
        if processed.has_files or processed.has_transcript:
            logger.info(
                "files.user_file_received",
                user_id=user_id,
                file_type=content_type,
            )

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            "unified_handler.failed",
            user_id=user_id,
            message_id=message.message_id,
            content_type=content_type,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )

        # Send error message to user
        error_msg = _get_error_message(content_type)
        try:
            await message.answer(error_msg)
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Ignore send errors

    finally:
        # Mark normalization complete if not already done
        # (in case of error before step 4)
        if not normalization_finished:
            await tracker.finish(chat_id, message.message_id)


def _get_content_type(message: types.Message) -> str:  # pylint: disable=too-many-return-statements
    """Determine content type for metrics and logging.

    Args:
        message: Telegram message.

    Returns:
        Content type string.
    """
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.audio:
        return "audio"
    if message.video:
        return "video"
    if message.photo:
        return "photo"
    if message.document:
        return "document"
    return "text"


def _get_error_message(content_type: str) -> str:
    """Get user-friendly error message.

    Args:
        content_type: Content type that failed.

    Returns:
        Error message string.
    """
    messages = {
        "voice": "Failed to process voice message. Please try again.",
        "video_note": "Failed to process video note. Please try again.",
        "audio": "Failed to process audio file. Please try again later.",
        "video": "Failed to process video file. Please try again later.",
        "photo": "Failed to upload photo. Please try again later.",
        "document": "Failed to upload document. Please try again later.",
        "text": "Failed to process message. Please try again.",
    }
    return messages.get(content_type, "An error occurred. Please try again.")


async def _charge_transcription(
    session: AsyncSession,
    user_id: int,
    message_id: int,
    transcript: TranscriptInfo,
    content_type: str,
) -> None:
    """Charge user for Whisper transcription.

    Args:
        session: Database session.
        user_id: User ID.
        message_id: Message ID.
        transcript: Transcription info with cost.
        content_type: Content type (voice, video_note).
    """
    from decimal import Decimal  # pylint: disable=import-outside-toplevel

    from db.repositories.balance_operation_repository import \
        BalanceOperationRepository  # pylint: disable=import-outside-toplevel
    from db.repositories.user_repository import \
        UserRepository  # pylint: disable=import-outside-toplevel
    from services.balance_service import \
        BalanceService  # pylint: disable=import-outside-toplevel
    from telegram.pipeline.models import \
        TranscriptInfo  # pylint: disable=import-outside-toplevel

    try:
        whisper_cost = Decimal(str(transcript.cost_usd))

        user_repo = UserRepository(session)
        balance_op_repo = BalanceOperationRepository(session)
        balance_service = BalanceService(session, user_repo, balance_op_repo)

        duration = int(transcript.duration_seconds)
        description = f"Whisper API: {content_type} transcription, {duration}s"

        await balance_service.charge_user(
            user_id=user_id,
            amount=whisper_cost,
            description=description,
            related_message_id=message_id,
        )

        await session.commit()

        logger.info(
            "unified_handler.transcription_charged",
            user_id=user_id,
            cost_usd=float(whisper_cost),
            duration=duration,
            content_type=content_type,
        )

        # Log as tool usage for Grafana costs dashboard
        # Auto-transcription uses the same Whisper API as transcribe_audio tool
        logger.info(
            "tools.loop.user_charged_for_tool",
            user_id=user_id,
            tool_name="transcribe_audio",
            cost_usd=float(whisper_cost),
        )

    except Exception as charge_error:  # pylint: disable=broad-exception-caught
        logger.error(
            "unified_handler.charge_failed",
            user_id=user_id,
            cost_usd=transcript.cost_usd,
            error=str(charge_error),
            exc_info=True,
            msg="CRITICAL: Failed to charge user for Whisper!",
        )
        # Don't fail the request - user already got the transcription
