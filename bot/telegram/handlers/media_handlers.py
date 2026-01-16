"""Media handlers for all Telegram media types.

Two handling strategies based on media type:

1. Voice messages & video notes (user "speech"):
   - Auto-transcribe with Whisper
   - Pass transcript via queue to Claude
   - User pays for transcription

2. Audio files (MP3, FLAC) & video files (MP4, MOV):
   - Upload to Claude Files API
   - Save to user_files table
   - NO auto-transcription (Claude uses transcribe_audio tool if needed)
   - Enables file processing (convert, analyze, etc.)
"""

from aiogram import F
from aiogram import Router
from aiogram import types
import openai
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.media_processor import download_media
from telegram.media_processor import get_or_create_thread
from telegram.media_processor import MediaContent
from telegram.media_processor import MediaProcessor
from telegram.media_processor import MediaType
from utils.metrics import record_message_received
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Router for all media handlers
router = Router(name="media")

# Global MediaProcessor instance
_media_processor: MediaProcessor | None = None


def get_media_processor() -> MediaProcessor:
    """Get or create global MediaProcessor instance.

    Returns:
        MediaProcessor instance.
    """
    global _media_processor  # pylint: disable=global-statement
    if _media_processor is None:
        _media_processor = MediaProcessor()
        logger.info("media_handlers.processor_initialized")
    return _media_processor


@router.message(F.voice)
async def handle_voice(message: types.Message, session: AsyncSession) -> None:
    """Handle voice messages with automatic transcription.

    Phase 1.6: Universal media architecture.
    Voice messages transcribed with Whisper, passed via queue.

    Args:
        message: Telegram message with voice recording.
        session: Database session (injected by DatabaseMiddleware).
    """
    if not message.from_user or not message.voice:
        logger.warning("voice_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    voice = message.voice

    logger.info("voice_handler.received",
                user_id=user_id,
                message_id=message.message_id,
                duration=voice.duration,
                file_size=voice.file_size)

    # Record metrics
    record_message_received(chat_type=message.chat.type, content_type="voice")

    try:
        # 1. Download voice from Telegram
        audio_bytes = await download_media(message, MediaType.VOICE)

        logger.info("voice_handler.download_complete",
                    user_id=user_id,
                    size_bytes=len(audio_bytes))

        # 2. Process with MediaProcessor (transcribe)
        processor = get_media_processor()
        filename = f"voice_{voice.file_id[:8]}.ogg"

        media_content = await processor.process_voice(audio_bytes=audio_bytes,
                                                      filename=filename,
                                                      duration=voice.duration)

        logger.info("voice_handler.transcribed",
                    user_id=user_id,
                    transcript_length=len(media_content.text_content or ""),
                    cost_usd=media_content.metadata.get("cost_usd"))

        # Phase 2.1: Charge user for Whisper API transcription
        if "cost_usd" in media_content.metadata:
            try:
                from decimal import \
                    Decimal  # pylint: disable=import-outside-toplevel

                from db.repositories.balance_operation_repository import \
                    BalanceOperationRepository  # pylint: disable=import-outside-toplevel
                from db.repositories.user_repository import \
                    UserRepository  # pylint: disable=import-outside-toplevel
                from services.balance_service import \
                    BalanceService  # pylint: disable=import-outside-toplevel

                whisper_cost = Decimal(str(media_content.metadata["cost_usd"]))

                user_repo = UserRepository(session)
                balance_op_repo = BalanceOperationRepository(session)
                balance_service = BalanceService(session, user_repo,
                                                 balance_op_repo)

                await balance_service.charge_user(
                    user_id=user_id,
                    amount=whisper_cost,
                    description=
                    f"Whisper API: voice transcription, {voice.duration}s",
                    related_message_id=message.message_id,
                )

                await session.commit()

                logger.info("voice_handler.user_charged",
                            user_id=user_id,
                            cost_usd=float(whisper_cost))

            except Exception as charge_error:  # pylint: disable=broad-exception-caught
                logger.error("voice_handler.charge_user_error",
                             user_id=user_id,
                             cost_usd=media_content.metadata.get("cost_usd"),
                             error=str(charge_error),
                             exc_info=True,
                             msg="CRITICAL: Failed to charge user for Whisper!")
                # Don't fail - user already got transcription

        # 3. Get thread_id
        thread = await get_or_create_thread(message, session)
        await session.commit()

        logger.info("voice_handler.thread_resolved",
                    user_id=user_id,
                    thread_id=thread.id)

        # 4. Pass to queue (Claude handler will save to DB)
        from telegram.handlers.claude import \
            message_queue_manager  # pylint: disable=import-outside-toplevel

        if message_queue_manager is None:
            logger.error("voice_handler.queue_not_initialized")
            await message.answer(
                "Bot is not properly configured. Please contact administrator.")
            return

        # Add to queue with immediate processing (no 200ms delay)
        await message_queue_manager.add_message(thread.id,
                                                message,
                                                media_content=media_content,
                                                immediate=True)

        logger.info("voice_handler.complete",
                    user_id=user_id,
                    thread_id=thread.id,
                    transcript_length=len(media_content.text_content or ""))

    except openai.APIError as e:
        logger.error("voice_handler.whisper_api_failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to transcribe voice message. Please try again.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("voice_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to process voice message. Please try again later.")


@router.message(F.audio)
async def handle_audio(message: types.Message, session: AsyncSession) -> None:
    """Handle audio files by uploading to Files API.

    Audio files (MP3, FLAC, WAV, etc.) are uploaded and saved for later use.
    Claude can transcribe them using transcribe_audio tool if needed.

    Unlike voice messages which are auto-transcribed (spoken input from user),
    audio files are treated as files to be processed on demand.

    Args:
        message: Telegram message with audio file.
        session: Database session (injected by DatabaseMiddleware).
    """
    # pylint: disable=import-outside-toplevel
    from datetime import datetime
    from datetime import timedelta
    from datetime import timezone

    from config import FILES_API_TTL_HOURS
    from core.claude.files_api import upload_to_files_api
    from db.models.user_file import FileSource
    from db.models.user_file import FileType
    from db.repositories.user_file_repository import UserFileRepository

    if not message.from_user or not message.audio:
        logger.warning("audio_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    audio = message.audio
    filename = audio.file_name or f"audio_{audio.file_id[:8]}.mp3"
    mime_type = audio.mime_type or "audio/mpeg"

    logger.info("audio_handler.received",
                user_id=user_id,
                message_id=message.message_id,
                filename=filename,
                duration=audio.duration,
                file_size=audio.file_size,
                mime_type=mime_type)

    # Record metrics
    record_message_received(chat_type=message.chat.type, content_type="audio")

    try:
        # 1. Download audio from Telegram
        audio_bytes = await download_media(message, MediaType.AUDIO)

        logger.info("audio_handler.download_complete",
                    user_id=user_id,
                    size_bytes=len(audio_bytes))

        # 2. Upload to Files API (so Claude can process it)
        claude_file_id = await upload_to_files_api(file_bytes=audio_bytes,
                                                   filename=filename,
                                                   mime_type=mime_type)

        logger.info("audio_handler.files_api_complete",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id)

        # 3. Get or create thread
        thread = await get_or_create_thread(message, session)

        # 4. Save to database
        user_file_repo = UserFileRepository(session)
        await user_file_repo.create(
            message_id=message.message_id,
            telegram_file_id=audio.file_id,
            telegram_file_unique_id=audio.file_unique_id,
            claude_file_id=claude_file_id,
            filename=filename,
            file_type=FileType.AUDIO,
            mime_type=mime_type,
            file_size=audio.file_size or len(audio_bytes),
            source=FileSource.USER,
            expires_at=datetime.now(timezone.utc) +
            timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={
                "duration": audio.duration,
                "performer": audio.performer,
                "title": audio.title,
            },
        )

        await session.commit()

        logger.info("audio_handler.saved",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id,
                    thread_id=thread.id)

        # 5. Create MediaContent for queue (no transcript, just file reference)
        media_content = MediaContent(
            type=MediaType.AUDIO,
            file_id=claude_file_id,
            text_content=None,  # No auto-transcription
            metadata={
                "filename": filename,
                "duration": audio.duration,
                "size_bytes": audio.file_size or len(audio_bytes),
                "mime_type": mime_type,
            })

        # 6. Queue for Claude handler
        from telegram.handlers.claude import message_queue_manager

        if message_queue_manager is None:
            logger.error("audio_handler.queue_not_initialized")
            await message.answer(
                "Bot is not properly configured. Please contact administrator.")
            return

        await message_queue_manager.add_message(thread.id,
                                                message,
                                                media_content=media_content,
                                                immediate=True)

        logger.info("audio_handler.complete",
                    user_id=user_id,
                    thread_id=thread.id,
                    claude_file_id=claude_file_id)

        # Dashboard tracking event
        logger.info("files.user_file_received",
                    user_id=user_id,
                    file_type="audio")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("audio_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "Failed to process audio file. Please try again later.")


@router.message(F.video)
async def handle_video(message: types.Message, session: AsyncSession) -> None:
    """Handle video files by uploading to Files API.

    Video files (MP4, MOV, AVI, etc.) are uploaded and saved for later use.
    Claude can transcribe them using transcribe_audio tool if needed.

    Unlike video_notes (round videos) which are auto-transcribed (spoken input),
    video files are treated as files to be processed on demand.

    Args:
        message: Telegram message with video file.
        session: Database session (injected by DatabaseMiddleware).
    """
    # pylint: disable=import-outside-toplevel
    from datetime import datetime
    from datetime import timedelta
    from datetime import timezone

    from config import FILES_API_TTL_HOURS
    from core.claude.files_api import upload_to_files_api
    from db.models.user_file import FileSource
    from db.models.user_file import FileType
    from db.repositories.user_file_repository import UserFileRepository

    if not message.from_user or not message.video:
        logger.warning("video_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    video = message.video
    filename = video.file_name or f"video_{video.file_id[:8]}.mp4"
    mime_type = video.mime_type or "video/mp4"

    logger.info("video_handler.received",
                user_id=user_id,
                message_id=message.message_id,
                filename=filename,
                duration=video.duration,
                file_size=video.file_size,
                mime_type=mime_type)

    # Record metrics
    record_message_received(chat_type=message.chat.type, content_type="video")

    try:
        # 1. Download video from Telegram
        video_bytes = await download_media(message, MediaType.VIDEO)

        logger.info("video_handler.download_complete",
                    user_id=user_id,
                    size_bytes=len(video_bytes))

        # 2. Upload to Files API (so Claude can process it)
        claude_file_id = await upload_to_files_api(file_bytes=video_bytes,
                                                   filename=filename,
                                                   mime_type=mime_type)

        logger.info("video_handler.files_api_complete",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id)

        # 3. Get or create thread
        thread = await get_or_create_thread(message, session)

        # 4. Save to database
        user_file_repo = UserFileRepository(session)
        await user_file_repo.create(
            message_id=message.message_id,
            telegram_file_id=video.file_id,
            telegram_file_unique_id=video.file_unique_id,
            claude_file_id=claude_file_id,
            filename=filename,
            file_type=FileType.VIDEO,
            mime_type=mime_type,
            file_size=video.file_size or len(video_bytes),
            source=FileSource.USER,
            expires_at=datetime.now(timezone.utc) +
            timedelta(hours=FILES_API_TTL_HOURS),
            file_metadata={
                "duration": video.duration,
                "width": video.width,
                "height": video.height,
            },
        )

        await session.commit()

        logger.info("video_handler.saved",
                    user_id=user_id,
                    filename=filename,
                    claude_file_id=claude_file_id,
                    thread_id=thread.id)

        # 5. Create MediaContent for queue (no transcript, just file reference)
        media_content = MediaContent(
            type=MediaType.VIDEO,
            file_id=claude_file_id,
            text_content=None,  # No auto-transcription
            metadata={
                "filename": filename,
                "duration": video.duration,
                "size_bytes": video.file_size or len(video_bytes),
                "mime_type": mime_type,
            })

        # 6. Queue for Claude handler
        from telegram.handlers.claude import message_queue_manager

        if message_queue_manager is None:
            logger.error("video_handler.queue_not_initialized")
            await message.answer(
                "Bot is not properly configured. Please contact administrator.")
            return

        await message_queue_manager.add_message(thread.id,
                                                message,
                                                media_content=media_content,
                                                immediate=True)

        logger.info("video_handler.complete",
                    user_id=user_id,
                    thread_id=thread.id,
                    claude_file_id=claude_file_id)

        # Dashboard tracking event
        logger.info("files.user_file_received",
                    user_id=user_id,
                    file_type="video")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("video_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "Failed to process video file. Please try again later.")


@router.message(F.video_note)
async def handle_video_note(message: types.Message,
                            session: AsyncSession) -> None:
    """Handle round video messages (video notes).

    Phase 1.6: Round videos from Telegram mobile app.
    Audio track transcribed with Whisper.

    Args:
        message: Telegram message with video note.
        session: Database session (injected by DatabaseMiddleware).
    """
    if not message.from_user or not message.video_note:
        logger.warning("video_note_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    video_note = message.video_note

    logger.info("video_note_handler.received",
                user_id=user_id,
                message_id=message.message_id,
                duration=video_note.duration,
                file_size=video_note.file_size)

    # Record metrics
    record_message_received(chat_type=message.chat.type,
                            content_type="video_note")

    try:
        # 1. Download video note
        video_bytes = await download_media(message, MediaType.VIDEO_NOTE)

        logger.info("video_note_handler.download_complete",
                    user_id=user_id,
                    size_bytes=len(video_bytes))

        # 2. Process (transcribe audio)
        processor = get_media_processor()
        filename = f"video_note_{video_note.file_id[:8]}.mp4"

        media_content = await processor.process_video(
            video_bytes=video_bytes,
            filename=filename,
            duration=video_note.duration)

        logger.info("video_note_handler.transcribed",
                    user_id=user_id,
                    transcript_length=len(media_content.text_content or ""),
                    cost_usd=media_content.metadata.get("cost_usd"))

        # Phase 2.1: Charge user for Whisper API transcription
        if "cost_usd" in media_content.metadata:
            try:
                from decimal import \
                    Decimal  # pylint: disable=import-outside-toplevel

                from db.repositories.balance_operation_repository import \
                    BalanceOperationRepository  # pylint: disable=import-outside-toplevel
                from db.repositories.user_repository import \
                    UserRepository  # pylint: disable=import-outside-toplevel
                from services.balance_service import \
                    BalanceService  # pylint: disable=import-outside-toplevel

                whisper_cost = Decimal(str(media_content.metadata["cost_usd"]))

                user_repo = UserRepository(session)
                balance_op_repo = BalanceOperationRepository(session)
                balance_service = BalanceService(session, user_repo,
                                                 balance_op_repo)

                await balance_service.charge_user(
                    user_id=user_id,
                    amount=whisper_cost,
                    description=
                    f"Whisper API: video note transcription, {video_note.duration}s",
                    related_message_id=message.message_id,
                )

                await session.commit()

                logger.info("video_note_handler.user_charged",
                            user_id=user_id,
                            cost_usd=float(whisper_cost))

            except Exception as charge_error:  # pylint: disable=broad-exception-caught
                logger.error("video_note_handler.charge_user_error",
                             user_id=user_id,
                             cost_usd=media_content.metadata.get("cost_usd"),
                             error=str(charge_error),
                             exc_info=True,
                             msg="CRITICAL: Failed to charge user for Whisper!")
                # Don't fail - user already got transcription

        # 3. Get thread
        thread = await get_or_create_thread(message, session)
        await session.commit()

        # 4. Queue
        from telegram.handlers.claude import \
            message_queue_manager  # pylint: disable=import-outside-toplevel

        if message_queue_manager is None:
            logger.error("video_note_handler.queue_not_initialized")
            await message.answer(
                "Bot is not properly configured. Please contact administrator.")
            return

        await message_queue_manager.add_message(thread.id,
                                                message,
                                                media_content=media_content,
                                                immediate=True)

        logger.info("video_note_handler.complete",
                    user_id=user_id,
                    thread_id=thread.id)

    except openai.APIError as e:
        logger.error("video_note_handler.whisper_api_failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to transcribe video note. Please try again.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("video_note_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to process video note. Please try again later.")
