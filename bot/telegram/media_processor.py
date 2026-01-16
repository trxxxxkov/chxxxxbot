"""Universal media processor for all Telegram media types.

Phase 1.6: Unified architecture for voice, audio, video, photo, document.

This module provides:
- MediaType enum (categorization)
- MediaContent dataclass (processed result)
- MediaProcessor class (universal processing)
- Helper functions (download, thread resolution)

Architecture principle:
All media types follow the same flow:
1. Handler receives media → 2. MediaProcessor processes → 3. Queue with MediaContent
→ 4. Claude handler saves to DB

NO ad-hoc solutions, NO direct DB saves before queue.
"""

from dataclasses import dataclass
from enum import Enum
import io
from typing import Optional

from aiogram import types
from core.clients import get_anthropic_async_client
from core.clients import get_openai_async_client
from core.pricing import calculate_whisper_cost
from core.pricing import cost_to_float
from db.models.thread import Thread
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class MediaType(str, Enum):
    """Media type classification.

    Used to determine processing strategy and DB storage format.
    """

    VOICE = "voice"  # Voice message (OGG/OPUS) → Whisper transcript
    AUDIO = "audio"  # Audio file (MP3/M4A/WAV/FLAC) → Whisper transcript
    VIDEO = "video"  # Video file → Whisper transcript (audio track)
    VIDEO_NOTE = "video_note"  # Round video message → Whisper transcript
    IMAGE = "image"  # Photo → Files API upload (vision)
    DOCUMENT = "document"  # Document (PDF/TXT/etc) → Files API or text extract


@dataclass
class MediaContent:
    """Processed media content ready for Claude.

    Universal container for all media processing results.
    Contains either transcript (for audio/video) or file_id (for vision).

    Attributes:
        type: Media type classification.
        text_content: Transcript for voice/audio/video, or None.
        file_id: Files API ID for images/PDFs, or None.
        metadata: Additional info (duration, cost, size, mime_type, etc).
    """

    type: MediaType
    text_content: Optional[str] = None
    file_id: Optional[str] = None
    metadata: dict = None

    def __post_init__(self) -> None:
        """Initialize metadata dict if None."""
        if self.metadata is None:
            self.metadata = {}


class MediaProcessor:
    """Universal processor for all Telegram media types.

    Phase 1.6: Single class handles all media with consistent interface.

    Architecture:
    - All methods return MediaContent (unified output)
    - All methods are async (network I/O)
    - All methods log cost and metadata
    - No direct DB access (handlers do thread resolution)
    - Uses centralized client factories from core.clients

    Example:
        processor = MediaProcessor()

        # Voice message
        audio_bytes = await download_media(message)
        content = await processor.process_voice(audio_bytes, "voice.ogg", 15)
        # Returns: MediaContent(type=VOICE, text_content="transcript", ...)

        # Image
        image_bytes = await download_media(message)
        content = await processor.process_image(image_bytes, "photo.jpg")
        # Returns: MediaContent(type=IMAGE, file_id="file_abc", ...)
    """

    async def process_voice(self,
                            audio_bytes: bytes,
                            filename: str,
                            duration: int,
                            language: Optional[str] = None) -> MediaContent:
        """Process voice message with Whisper transcription.

        Voice messages are OGG/OPUS format, usually 5-60 seconds.
        Transcribed to text for natural conversation flow.

        Args:
            audio_bytes: Voice audio data (OGG/OPUS).
            filename: Original filename (for Whisper API).
            duration: Duration in seconds (for cost calculation).
            language: Optional language code (None = auto-detect).

        Returns:
            MediaContent with transcript in text_content.

        Raises:
            openai.APIError: Whisper API failure.
        """
        # Use centralized client factory
        client = get_openai_async_client()

        # Prepare audio file
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        logger.info("media_processor.transcribing_voice",
                    filename=filename,
                    duration=duration,
                    size_bytes=len(audio_bytes))

        # Call Whisper API
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language,  # None = auto-detect
            response_format="text"  # Simple text format
        )

        transcript = response.strip()

        # Use centralized pricing calculation
        cost_usd = calculate_whisper_cost(duration)

        logger.info("media_processor.voice_transcribed",
                    filename=filename,
                    transcript_length=len(transcript),
                    transcript_preview=transcript[:100],
                    duration=duration,
                    cost_usd=cost_to_float(cost_usd),
                    language=language or "auto")

        return MediaContent(type=MediaType.VOICE,
                            text_content=transcript,
                            file_id=None,
                            metadata={
                                "duration": duration,
                                "cost_usd": cost_to_float(cost_usd),
                                "language": language or "auto",
                                "size_bytes": len(audio_bytes),
                            })

    async def process_audio(self,
                            audio_bytes: bytes,
                            filename: str,
                            duration: Optional[int] = None,
                            language: Optional[str] = None) -> MediaContent:
        """Process audio file with Whisper transcription.

        Audio files: MP3, M4A, WAV, FLAC, OGG.
        Longer than voice messages, can be music/podcasts/recordings.

        Args:
            audio_bytes: Audio file data.
            filename: Original filename (for Whisper API).
            duration: Duration in seconds (for cost), or None.
            language: Optional language code (None = auto-detect).

        Returns:
            MediaContent with transcript in text_content.

        Raises:
            openai.APIError: Whisper API failure.
        """
        # Use centralized client factory
        client = get_openai_async_client()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        logger.info("media_processor.transcribing_audio",
                    filename=filename,
                    size_bytes=len(audio_bytes))

        # Call Whisper API (verbose_json for duration)
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language,
            response_format="verbose_json"  # Get duration from response
        )

        transcript = response.text.strip()
        detected_duration = response.duration
        detected_language = response.language

        # Use centralized pricing calculation
        cost_usd = calculate_whisper_cost(detected_duration)

        logger.info("media_processor.audio_transcribed",
                    filename=filename,
                    transcript_length=len(transcript),
                    duration=detected_duration,
                    cost_usd=cost_to_float(cost_usd),
                    language=detected_language)

        return MediaContent(type=MediaType.AUDIO,
                            text_content=transcript,
                            file_id=None,
                            metadata={
                                "duration": detected_duration,
                                "cost_usd": cost_to_float(cost_usd),
                                "language": detected_language,
                                "size_bytes": len(audio_bytes),
                                "filename": filename,
                            })

    async def process_video(self,
                            video_bytes: bytes,
                            filename: str,
                            duration: Optional[int] = None,
                            language: Optional[str] = None) -> MediaContent:
        """Process video file by transcribing audio track.

        Phase 1.6: Extract audio track and transcribe with Whisper.
        Video frames NOT analyzed (no video vision API yet).

        Args:
            video_bytes: Video file data (MP4, MOV, AVI, etc).
            filename: Original filename.
            duration: Duration in seconds, or None.
            language: Optional language code.

        Returns:
            MediaContent with transcript in text_content.

        Raises:
            openai.APIError: Whisper API failure.

        Note:
            Whisper API accepts video files directly and extracts audio.
            No need for separate ffmpeg processing.
        """
        # Use centralized client factory
        client = get_openai_async_client()

        video_file = io.BytesIO(video_bytes)
        video_file.name = filename

        logger.info("media_processor.transcribing_video",
                    filename=filename,
                    size_bytes=len(video_bytes))

        # Whisper accepts video files (extracts audio automatically)
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=video_file,
            language=language,
            response_format="verbose_json")

        transcript = response.text.strip()
        detected_duration = response.duration
        detected_language = response.language

        # Use centralized pricing calculation
        cost_usd = calculate_whisper_cost(detected_duration)

        logger.info("media_processor.video_transcribed",
                    filename=filename,
                    transcript_length=len(transcript),
                    duration=detected_duration,
                    cost_usd=cost_to_float(cost_usd),
                    language=detected_language)

        return MediaContent(type=MediaType.VIDEO,
                            text_content=transcript,
                            file_id=None,
                            metadata={
                                "duration": detected_duration,
                                "cost_usd": cost_to_float(cost_usd),
                                "language": detected_language,
                                "size_bytes": len(video_bytes),
                                "filename": filename,
                            })

    async def process_image(self, image_bytes: bytes,
                            filename: str) -> MediaContent:
        """Process image by uploading to Files API.

        Phase 1.5: Images uploaded to Files API for Claude vision.
        Returns file_id that can be used in message content.

        Args:
            image_bytes: Image data (JPEG, PNG, GIF, WebP).
            filename: Original filename.

        Returns:
            MediaContent with file_id for Files API.

        Raises:
            anthropic.APIError: Files API upload failure.
        """
        # Use centralized client factory with Files API beta header
        client = get_anthropic_async_client(use_files_api=True)

        # Auto-detect MIME type using centralized module
        from core.mime_types import \
            detect_mime_type  # pylint: disable=import-outside-toplevel
        mime_type = detect_mime_type(filename=filename, file_bytes=image_bytes)

        logger.info("media_processor.uploading_image",
                    filename=filename,
                    mime_type=mime_type,
                    size_bytes=len(image_bytes))

        # Upload to Files API with detected MIME type
        file_response = await client.beta.files.upload(
            file=(filename, io.BytesIO(image_bytes), mime_type))

        file_id = file_response.id

        logger.info("media_processor.image_uploaded",
                    filename=filename,
                    file_id=file_id,
                    mime_type=mime_type,
                    size_bytes=len(image_bytes))

        return MediaContent(type=MediaType.IMAGE,
                            text_content=None,
                            file_id=file_id,
                            metadata={
                                "size_bytes": len(image_bytes),
                                "filename": filename,
                                "mime_type": mime_type,
                            })

    async def process_pdf(self, pdf_bytes: bytes,
                          filename: str) -> MediaContent:
        """Process PDF by uploading to Files API.

        Phase 1.5: PDFs uploaded to Files API for Claude PDF parsing.

        Args:
            pdf_bytes: PDF file data.
            filename: Original filename.

        Returns:
            MediaContent with file_id for Files API.

        Raises:
            anthropic.APIError: Files API upload failure.
        """
        # Use centralized client factory with Files API beta header
        client = get_anthropic_async_client(use_files_api=True)

        logger.info("media_processor.uploading_pdf",
                    filename=filename,
                    size_bytes=len(pdf_bytes))

        # Upload to Files API
        file_response = await client.beta.files.upload(
            file=(filename, io.BytesIO(pdf_bytes), "application/pdf"))

        file_id = file_response.id

        logger.info("media_processor.pdf_uploaded",
                    filename=filename,
                    file_id=file_id,
                    size_bytes=len(pdf_bytes))

        return MediaContent(type=MediaType.DOCUMENT,
                            text_content=None,
                            file_id=file_id,
                            metadata={
                                "size_bytes": len(pdf_bytes),
                                "filename": filename,
                                "mime_type": "application/pdf",
                            })


async def download_media(message: types.Message,
                         media_type: MediaType) -> bytes:
    """Download media from Telegram.

    Universal download function for all media types.

    Args:
        message: Telegram message with media.
        media_type: Type of media to download.

    Returns:
        Media bytes.

    Raises:
        ValueError: Invalid media type or download failure.
    """
    # Get file_id based on media type
    if media_type == MediaType.VOICE and message.voice:
        file_id = message.voice.file_id
    elif media_type == MediaType.AUDIO and message.audio:
        file_id = message.audio.file_id
    elif media_type == MediaType.VIDEO and message.video:
        file_id = message.video.file_id
    elif media_type == MediaType.VIDEO_NOTE and message.video_note:
        file_id = message.video_note.file_id
    elif media_type == MediaType.IMAGE and message.photo:
        file_id = message.photo[-1].file_id  # Largest size
    elif media_type == MediaType.DOCUMENT and message.document:
        file_id = message.document.file_id
    else:
        raise ValueError(f"Invalid media type or media not found: {media_type}")

    # Download from Telegram
    file_info = await message.bot.get_file(file_id)
    file_bytes_io = await message.bot.download_file(file_info.file_path)

    if not file_bytes_io:
        raise ValueError(f"Failed to download {media_type} from Telegram")

    return file_bytes_io.read()


async def get_or_create_thread(message: types.Message,
                               session: AsyncSession) -> Thread:
    """Get or create thread for message (DRY helper).

    Phase 1.6: Extracted from handlers to avoid code duplication.
    All media handlers use this function.

    Args:
        message: Telegram message.
        session: Database session.

    Returns:
        Thread for this message.

    Raises:
        ValueError: Missing from_user or chat.
    """
    if not message.from_user:
        raise ValueError("Message has no from_user")

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Get or create user
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(
        telegram_id=user_id,
        is_bot=message.from_user.is_bot,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code,
        is_premium=message.from_user.is_premium or False,
        added_to_attachment_menu=(message.from_user.added_to_attachment_menu or
                                  False),
    )

    # Get or create chat
    chat_repo = ChatRepository(session)
    chat, _ = await chat_repo.get_or_create(
        telegram_id=chat_id,
        chat_type=message.chat.type,
        title=message.chat.title,
        username=message.chat.username,
        first_name=message.chat.first_name,
        last_name=message.chat.last_name,
        is_forum=message.chat.is_forum or False,
    )

    # Get or create thread
    thread_repo = ThreadRepository(session)

    # Generate thread title from chat/user info
    thread_title = (
        message.chat.title  # Groups/supergroups
        or message.chat.first_name  # Private chats
        or message.from_user.first_name if message.from_user else None)

    thread, was_created = await thread_repo.get_or_create_thread(
        chat_id=chat_id,
        user_id=user_id,
        thread_id=message.message_thread_id,
        title=thread_title,
    )

    # Dashboard tracking events (same as claude_handler for consistency)
    if was_created:
        logger.info("claude_handler.thread_created",
                    thread_id=thread.id,
                    user_id=user_id,
                    telegram_thread_id=message.message_thread_id)

    # Log message received for dashboard tracking
    logger.info("claude_handler.message_received",
                chat_id=chat_id,
                user_id=user_id,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                is_topic_message=message.is_topic_message,
                text_length=len(message.text or message.caption or ""),
                is_new_thread="true" if was_created else "false")

    logger.debug("media_processor.thread_resolved",
                 user_id=user_id,
                 chat_id=chat_id,
                 thread_id=thread.id,
                 telegram_thread_id=message.message_thread_id)

    return thread
