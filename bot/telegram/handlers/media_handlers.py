"""Universal media handlers for all Telegram media types.

Phase 1.6: Unified architecture using MediaProcessor.

All media handlers follow the same pattern:
1. Download media from Telegram
2. Process with MediaProcessor (transcribe/upload)
3. Get thread_id
4. Pass MediaContent via queue → Claude handler

NO ad-hoc solutions, NO direct DB saves before queue.
"""

from aiogram import F
from aiogram import Router
from aiogram import types
import openai
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.media_processor import download_media
from telegram.media_processor import get_or_create_thread
from telegram.media_processor import MediaProcessor
from telegram.media_processor import MediaType
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
    """Handle audio files with automatic transcription.

    Phase 1.6: MP3, M4A, WAV, FLAC, OGG files.
    Transcribed with Whisper, passed via queue.

    Args:
        message: Telegram message with audio file.
        session: Database session (injected by DatabaseMiddleware).
    """
    if not message.from_user or not message.audio:
        logger.warning("audio_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    audio = message.audio

    logger.info("audio_handler.received",
                user_id=user_id,
                message_id=message.message_id,
                filename=audio.file_name,
                duration=audio.duration,
                file_size=audio.file_size,
                mime_type=audio.mime_type)

    try:
        # 1. Download audio
        audio_bytes = await download_media(message, MediaType.AUDIO)

        logger.info("audio_handler.download_complete",
                    user_id=user_id,
                    size_bytes=len(audio_bytes))

        # 2. Process (transcribe)
        processor = get_media_processor()
        filename = audio.file_name or f"audio_{audio.file_id[:8]}.mp3"

        media_content = await processor.process_audio(audio_bytes=audio_bytes,
                                                      filename=filename,
                                                      duration=audio.duration)

        logger.info("audio_handler.transcribed",
                    user_id=user_id,
                    transcript_length=len(media_content.text_content or ""),
                    cost_usd=media_content.metadata.get("cost_usd"))

        # 3. Get thread
        thread = await get_or_create_thread(message, session)
        await session.commit()

        # 4. Queue
        from telegram.handlers.claude import \
            message_queue_manager  # pylint: disable=import-outside-toplevel

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
                    thread_id=thread.id)

    except openai.APIError as e:
        logger.error("audio_handler.whisper_api_failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to transcribe audio file. Please try again.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("audio_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to process audio file. Please try again later.")


@router.message(F.video)
async def handle_video(message: types.Message, session: AsyncSession) -> None:
    """Handle video files by transcribing audio track.

    Phase 1.6: MP4, MOV, AVI files.
    Audio track extracted and transcribed with Whisper.

    Args:
        message: Telegram message with video file.
        session: Database session (injected by DatabaseMiddleware).
    """
    if not message.from_user or not message.video:
        logger.warning("video_handler.invalid_message",
                       message_id=message.message_id)
        return

    user_id = message.from_user.id
    video = message.video

    logger.info("video_handler.received",
                user_id=user_id,
                message_id=message.message_id,
                duration=video.duration,
                file_size=video.file_size,
                mime_type=video.mime_type)

    try:
        # 1. Download video
        video_bytes = await download_media(message, MediaType.VIDEO)

        logger.info("video_handler.download_complete",
                    user_id=user_id,
                    size_bytes=len(video_bytes))

        # 2. Process (transcribe audio track)
        processor = get_media_processor()
        filename = video.file_name or f"video_{video.file_id[:8]}.mp4"

        media_content = await processor.process_video(video_bytes=video_bytes,
                                                      filename=filename,
                                                      duration=video.duration)

        logger.info("video_handler.transcribed",
                    user_id=user_id,
                    transcript_length=len(media_content.text_content or ""),
                    cost_usd=media_content.metadata.get("cost_usd"))

        # 3. Get thread
        thread = await get_or_create_thread(message, session)
        await session.commit()

        # 4. Queue
        from telegram.handlers.claude import \
            message_queue_manager  # pylint: disable=import-outside-toplevel

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
                    thread_id=thread.id)

    except openai.APIError as e:
        logger.error("video_handler.whisper_api_failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to transcribe video audio. Please try again.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("video_handler.failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer(
            "❌ Failed to process video file. Please try again later.")


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
