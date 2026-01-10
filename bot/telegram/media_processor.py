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
from anthropic import AsyncAnthropic
from db.models.thread import Thread
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
import openai
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

    def __init__(self) -> None:
        """Initialize processor with API clients."""
        self._openai_client: Optional[openai.AsyncOpenAI] = None
        self._anthropic_client: Optional[AsyncAnthropic] = None

    def _get_openai_client(self) -> openai.AsyncOpenAI:
        """Lazy initialize OpenAI client (for Whisper).

        Returns:
            OpenAI async client.
        """
        if self._openai_client is None:
            # Import here to avoid circular dependency
            from main import \
                read_secret  # pylint: disable=import-outside-toplevel
            api_key = read_secret("openai_api_key")
            self._openai_client = openai.AsyncOpenAI(api_key=api_key)
            logger.info("media_processor.openai_initialized")
        return self._openai_client

    def _get_anthropic_client(self) -> AsyncAnthropic:
        """Lazy initialize Anthropic client (for Files API).

        Returns:
            Anthropic async client.
        """
        if self._anthropic_client is None:
            # Import here to avoid circular dependency
            from main import \
                read_secret  # pylint: disable=import-outside-toplevel
            api_key = read_secret("anthropic_api_key")
            self._anthropic_client = AsyncAnthropic(api_key=api_key)
            logger.info("media_processor.anthropic_initialized")
        return self._anthropic_client

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
        client = self._get_openai_client()

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

        # Calculate cost: $0.006 per minute
        cost_usd = (duration / 60.0) * 0.006

        logger.info("media_processor.voice_transcribed",
                    filename=filename,
                    transcript_length=len(transcript),
                    transcript_preview=transcript[:100],
                    duration=duration,
                    cost_usd=cost_usd,
                    language=language or "auto")

        return MediaContent(type=MediaType.VOICE,
                            text_content=transcript,
                            file_id=None,
                            metadata={
                                "duration": duration,
                                "cost_usd": cost_usd,
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
        client = self._get_openai_client()

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

        # Calculate cost
        cost_usd = (detected_duration / 60.0) * 0.006

        logger.info("media_processor.audio_transcribed",
                    filename=filename,
                    transcript_length=len(transcript),
                    duration=detected_duration,
                    cost_usd=cost_usd,
                    language=detected_language)

        return MediaContent(type=MediaType.AUDIO,
                            text_content=transcript,
                            file_id=None,
                            metadata={
                                "duration": detected_duration,
                                "cost_usd": cost_usd,
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
        client = self._get_openai_client()

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

        cost_usd = (detected_duration / 60.0) * 0.006

        logger.info("media_processor.video_transcribed",
                    filename=filename,
                    transcript_length=len(transcript),
                    duration=detected_duration,
                    cost_usd=cost_usd,
                    language=detected_language)

        return MediaContent(type=MediaType.VIDEO,
                            text_content=transcript,
                            file_id=None,
                            metadata={
                                "duration": detected_duration,
                                "cost_usd": cost_usd,
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
        client = self._get_anthropic_client()

        logger.info("media_processor.uploading_image",
                    filename=filename,
                    size_bytes=len(image_bytes))

        # Upload to Files API
        file_response = await client.files.create(file=(filename, image_bytes,
                                                        "image/jpeg"),
                                                  purpose="vision")

        file_id = file_response.id

        logger.info("media_processor.image_uploaded",
                    filename=filename,
                    file_id=file_id,
                    size_bytes=len(image_bytes))

        return MediaContent(type=MediaType.IMAGE,
                            text_content=None,
                            file_id=file_id,
                            metadata={
                                "size_bytes": len(image_bytes),
                                "filename": filename,
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
        client = self._get_anthropic_client()

        logger.info("media_processor.uploading_pdf",
                    filename=filename,
                    size_bytes=len(pdf_bytes))

        # Upload to Files API
        file_response = await client.files.create(file=(filename, pdf_bytes,
                                                        "application/pdf"),
                                                  purpose="vision")

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
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )

    # Get or create chat
    chat_repo = ChatRepository(session)
    chat, _ = await chat_repo.get_or_create(telegram_id=chat_id,
                                            chat_type=message.chat.type,
                                            title=message.chat.title)

    # Get or create thread
    thread_repo = ThreadRepository(session)
    thread, _ = await thread_repo.get_or_create_thread(
        chat_id=chat_id,
        user_id=user_id,
        thread_id=message.message_thread_id,
    )

    logger.debug("media_processor.thread_resolved",
                 user_id=user_id,
                 chat_id=chat_id,
                 thread_id=thread.id,
                 telegram_thread_id=message.message_thread_id)

    return thread
