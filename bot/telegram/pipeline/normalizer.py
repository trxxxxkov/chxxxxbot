"""Message normalizer for unified pipeline.

This module provides the MessageNormalizer class that converts any Telegram
message into a ProcessedMessage, performing all necessary I/O operations
(download, upload, transcribe) BEFORE the message enters the queue.

Key design principle:
All I/O happens in normalize() → ProcessedMessage is ready for immediate use.

Phase 3.2: Caches downloaded files in Redis for fast retrieval during tool execution.

NO __init__.py - use direct import:
    from telegram.pipeline.normalizer import MessageNormalizer
"""

from datetime import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

from aiogram import types
from cache.file_cache import cache_file
from core.claude.files_api import upload_to_files_api
from core.mime_types import detect_mime_type
from core.mime_types import is_audio_mime
from core.mime_types import is_image_mime
from core.mime_types import is_pdf_mime
from core.mime_types import is_video_mime
from core.pricing import calculate_whisper_cost
from core.pricing import cost_to_float
from telegram.chat_action import send_action
from telegram.context.extractors import extract_message_context
from telegram.context.extractors import get_sender_display
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import ReplyContext
from telegram.pipeline.models import TranscriptInfo
from telegram.pipeline.models import UploadedFile
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class MessageNormalizer:
    """Normalizes any Telegram message into ProcessedMessage.

    This class handles all media processing (download, upload, transcription)
    BEFORE the message enters the queue. This eliminates race conditions
    at the design level - all files are ready when ProcessedMessage is created.

    Processing strategy by media type:
    - VOICE, VIDEO_NOTE: Download → Transcribe with Whisper → TranscriptInfo
    - AUDIO, VIDEO: Download → Upload to Files API → UploadedFile
    - IMAGE: Download → Upload to Files API → UploadedFile
    - DOCUMENT, PDF: Download → Upload to Files API → UploadedFile

    Usage:
        normalizer = MessageNormalizer()
        processed = await normalizer.normalize(message)
        # processed.files contains already-uploaded files
        # processed.transcript contains completed transcription
    """

    def __init__(self) -> None:
        """Initialize the normalizer."""
        # Lazy import to avoid circular dependency
        self._openai_client = None
        logger.debug("normalizer.initialized")

    async def _get_openai_client(self):
        """Get or create OpenAI client for Whisper."""
        if self._openai_client is None:
            from core.clients import \
                get_openai_async_client  # pylint: disable=import-outside-toplevel
            self._openai_client = get_openai_async_client()
        return self._openai_client

    async def normalize(self, message: types.Message) -> ProcessedMessage:
        """Normalize a Telegram message into ProcessedMessage.

        This is the main entry point. It detects message type and delegates
        to appropriate processing methods.

        Args:
            message: Telegram message to normalize.

        Returns:
            ProcessedMessage with all I/O complete.

        Raises:
            ValueError: If message is invalid (no from_user).
        """
        if not message.from_user:
            raise ValueError("Message has no from_user")

        logger.info(
            "normalizer.processing",
            message_id=message.message_id,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            has_text=bool(message.text),
            has_caption=bool(message.caption),
            has_photo=bool(message.photo),
            has_document=bool(message.document),
            has_voice=bool(message.voice),
            has_audio=bool(message.audio),
            has_video=bool(message.video),
            has_video_note=bool(message.video_note),
        )

        # Extract metadata
        metadata = self._extract_metadata(message)

        # Extract reply context
        reply_context = self._extract_reply_context(message)

        # Get text content (text or caption)
        text = message.text or message.caption

        # Process media based on type
        files: list[UploadedFile] = []
        transcript: Optional[TranscriptInfo] = None
        transcription_charged = False

        # Send appropriate chat action for media processing
        if message.voice:
            await send_action(message.bot, message.chat.id, "record_voice",
                              message.message_thread_id)
            transcript, transcription_charged = await self._process_voice(
                message)
        elif message.video_note:
            await send_action(message.bot, message.chat.id, "record_video",
                              message.message_thread_id)
            transcript, transcription_charged = await self._process_video_note(
                message)
        elif message.audio:
            await send_action(message.bot, message.chat.id, "upload_voice",
                              message.message_thread_id)
            files = await self._process_audio(message)
        elif message.video:
            await send_action(message.bot, message.chat.id, "upload_video",
                              message.message_thread_id)
            files = await self._process_video(message)
        elif message.photo:
            await send_action(message.bot, message.chat.id, "upload_photo",
                              message.message_thread_id)
            files = await self._process_photo(message)
        elif message.document:
            await send_action(message.bot, message.chat.id, "upload_document",
                              message.message_thread_id)
            files = await self._process_document(message)

        processed = ProcessedMessage(
            text=text,
            metadata=metadata,
            original_message=message,
            files=files,
            transcript=transcript,
            reply_context=reply_context,
            transcription_charged=transcription_charged,
        )

        logger.info(
            "normalizer.complete",
            message_id=message.message_id,
            has_text=bool(processed.text),
            has_files=processed.has_files,
            has_transcript=processed.has_transcript,
            has_reply_context=processed.reply_context is not None,
            file_count=len(files),
        )

        return processed

    def _extract_metadata(self, message: types.Message) -> MessageMetadata:
        """Extract metadata from Telegram message.

        Args:
            message: Telegram message.

        Returns:
            MessageMetadata with all identifying information.
        """
        user = message.from_user

        return MessageMetadata(
            chat_id=message.chat.id,
            user_id=user.id if user else 0,
            message_id=message.message_id,
            message_thread_id=message.message_thread_id,
            chat_type=message.chat.type,
            date=message.date or datetime.now(timezone.utc),
            is_topic_message=message.is_topic_message or False,
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
            is_premium=user.is_premium or False if user else False,
        )

    def _extract_reply_context(
            self, message: types.Message) -> Optional[ReplyContext]:
        """Extract reply/forward/quote context.

        Args:
            message: Telegram message.

        Returns:
            ReplyContext or None if no context.
        """
        # Use existing extractor for basic info
        ctx = extract_message_context(message)

        # Check for forward
        if ctx.forward_origin:
            return ReplyContext(
                original_text=None,  # Forward origin doesn't include text
                original_sender=ctx.forward_origin.get("display"),
                original_message_id=ctx.forward_origin.get("message_id"),
                is_forward=True,
                is_quote=False,
                quote_text=None,
            )

        # Check for reply
        reply = message.reply_to_message
        if reply:
            quote_text = None
            is_quote = False

            # Check for quote (Bot API 9.3 feature)
            if ctx.quote_data:
                quote_text = ctx.quote_data.get("text")
                is_quote = True

            return ReplyContext(
                original_text=ctx.reply_snippet,
                original_sender=ctx.reply_sender_display,
                original_message_id=reply.message_id,
                is_forward=False,
                is_quote=is_quote,
                quote_text=quote_text,
            )

        return None

    async def _download_file(
        self,
        message: types.Message,
        file_id: str,
        filename: Optional[str] = None,
    ) -> bytes:
        """Download file from Telegram and cache for tools.

        Phase 3.2: Caches downloaded files in Redis for fast retrieval
        during tool execution (transcribe_audio, execute_python).

        Args:
            message: Telegram message (for bot access).
            file_id: Telegram file ID.
            filename: Optional filename for cache logging.

        Returns:
            File content as bytes.

        Raises:
            ValueError: If download fails.
        """
        file_info = await message.bot.get_file(file_id)
        file_bytes_io = await message.bot.download_file(file_info.file_path)

        if not file_bytes_io:
            raise ValueError(f"Failed to download file: {file_id}")

        content = file_bytes_io.read()

        # Phase 3.2: Cache file for potential tool use
        await cache_file(file_id, content, filename=filename)

        return content

    async def _process_voice(
        self,
        message: types.Message,
    ) -> tuple[Optional[TranscriptInfo], bool]:
        """Process voice message with Whisper transcription.

        Voice messages are automatically transcribed because they represent
        user speech input.

        Args:
            message: Telegram message with voice.

        Returns:
            Tuple of (TranscriptInfo, transcription_charged).

        Raises:
            openai.APIError: If Whisper API fails.
        """
        import io  # pylint: disable=import-outside-toplevel

        voice = message.voice
        user_id = message.from_user.id if message.from_user else 0

        logger.info(
            "normalizer.processing_voice",
            user_id=user_id,
            duration=voice.duration,
            file_size=voice.file_size,
        )

        # Download and cache
        voice_filename = f"voice_{voice.file_id[:8]}.ogg"
        audio_bytes = await self._download_file(message,
                                                voice.file_id,
                                                filename=voice_filename)

        # Transcribe
        client = await self._get_openai_client()
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = f"voice_{voice.file_id[:8]}.ogg"

        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=None,  # Auto-detect
            response_format="verbose_json",
        )

        transcript_text = response.text.strip()
        duration = response.duration or voice.duration
        detected_language = response.language or "auto"

        # Calculate cost
        cost_usd = cost_to_float(calculate_whisper_cost(duration))

        logger.info(
            "normalizer.voice_transcribed",
            user_id=user_id,
            transcript_length=len(transcript_text),
            duration=duration,
            language=detected_language,
            cost_usd=cost_usd,
        )

        transcript_info = TranscriptInfo(
            text=transcript_text,
            duration_seconds=duration,
            detected_language=detected_language,
            cost_usd=cost_usd,
        )

        # Charge will be handled by caller
        return transcript_info, False

    async def _process_video_note(
        self,
        message: types.Message,
    ) -> tuple[Optional[TranscriptInfo], bool]:
        """Process video note (round video) with Whisper transcription.

        Video notes are automatically transcribed because they represent
        user speech input (like voice messages but with video).

        Args:
            message: Telegram message with video_note.

        Returns:
            Tuple of (TranscriptInfo, transcription_charged).

        Raises:
            openai.APIError: If Whisper API fails.
        """
        import io  # pylint: disable=import-outside-toplevel

        video_note = message.video_note
        user_id = message.from_user.id if message.from_user else 0

        logger.info(
            "normalizer.processing_video_note",
            user_id=user_id,
            duration=video_note.duration,
            file_size=video_note.file_size,
        )

        # Download and cache
        video_note_filename = f"video_note_{video_note.file_id[:8]}.mp4"
        video_bytes = await self._download_file(message,
                                                video_note.file_id,
                                                filename=video_note_filename)

        # Transcribe (Whisper accepts video, extracts audio)
        client = await self._get_openai_client()
        video_file = io.BytesIO(video_bytes)
        video_file.name = f"video_note_{video_note.file_id[:8]}.mp4"

        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=video_file,
            language=None,
            response_format="verbose_json",
        )

        transcript_text = response.text.strip()
        duration = response.duration or video_note.duration
        detected_language = response.language or "auto"

        # Calculate cost
        cost_usd = cost_to_float(calculate_whisper_cost(duration))

        logger.info(
            "normalizer.video_note_transcribed",
            user_id=user_id,
            transcript_length=len(transcript_text),
            duration=duration,
            language=detected_language,
            cost_usd=cost_usd,
        )

        transcript_info = TranscriptInfo(
            text=transcript_text,
            duration_seconds=duration,
            detected_language=detected_language,
            cost_usd=cost_usd,
        )

        return transcript_info, False

    async def _process_audio(self,
                             message: types.Message) -> list[UploadedFile]:
        """Process audio file by uploading to Files API.

        Audio files are uploaded (not transcribed) - Claude can request
        transcription via the transcribe_audio tool if needed.

        Args:
            message: Telegram message with audio.

        Returns:
            List with single UploadedFile.
        """
        audio = message.audio
        user_id = message.from_user.id if message.from_user else 0

        filename = audio.file_name or f"audio_{audio.file_id[:8]}.mp3"

        logger.info(
            "normalizer.processing_audio",
            user_id=user_id,
            filename=filename,
            duration=audio.duration,
            file_size=audio.file_size,
        )

        # Download and cache
        audio_bytes = await self._download_file(message,
                                                audio.file_id,
                                                filename=filename)

        # Detect MIME
        mime_type = detect_mime_type(
            filename=filename,
            file_bytes=audio_bytes,
            declared_mime=audio.mime_type,
        )

        # Upload to Files API
        claude_file_id = await upload_to_files_api(
            file_bytes=audio_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        logger.info(
            "normalizer.audio_uploaded",
            user_id=user_id,
            filename=filename,
            claude_file_id=claude_file_id,
            size_bytes=len(audio_bytes),
        )

        return [
            UploadedFile(
                claude_file_id=claude_file_id,
                telegram_file_id=audio.file_id,
                telegram_file_unique_id=audio.file_unique_id,
                file_type=MediaType.AUDIO,
                filename=filename,
                mime_type=mime_type,
                size_bytes=audio.file_size or len(audio_bytes),
                metadata={
                    "duration": audio.duration,
                    "performer": audio.performer,
                    "title": audio.title,
                },
            )
        ]

    async def _process_video(self,
                             message: types.Message) -> list[UploadedFile]:
        """Process video file by uploading to Files API.

        Video files are uploaded (not transcribed) - Claude can request
        transcription via the transcribe_audio tool if needed.

        Args:
            message: Telegram message with video.

        Returns:
            List with single UploadedFile.
        """
        video = message.video
        user_id = message.from_user.id if message.from_user else 0

        filename = video.file_name or f"video_{video.file_id[:8]}.mp4"

        logger.info(
            "normalizer.processing_video",
            user_id=user_id,
            filename=filename,
            duration=video.duration,
            file_size=video.file_size,
        )

        # Download and cache
        video_bytes = await self._download_file(message,
                                                video.file_id,
                                                filename=filename)

        # Detect MIME
        mime_type = detect_mime_type(
            filename=filename,
            file_bytes=video_bytes,
            declared_mime=video.mime_type,
        )

        # Upload to Files API
        claude_file_id = await upload_to_files_api(
            file_bytes=video_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        logger.info(
            "normalizer.video_uploaded",
            user_id=user_id,
            filename=filename,
            claude_file_id=claude_file_id,
            size_bytes=len(video_bytes),
        )

        return [
            UploadedFile(
                claude_file_id=claude_file_id,
                telegram_file_id=video.file_id,
                telegram_file_unique_id=video.file_unique_id,
                file_type=MediaType.VIDEO,
                filename=filename,
                mime_type=mime_type,
                size_bytes=video.file_size or len(video_bytes),
                metadata={
                    "duration": video.duration,
                    "width": video.width,
                    "height": video.height,
                },
            )
        ]

    async def _process_photo(self,
                             message: types.Message) -> list[UploadedFile]:
        """Process photo by uploading to Files API.

        Args:
            message: Telegram message with photo.

        Returns:
            List with single UploadedFile.
        """
        # Get largest photo size
        photo = message.photo[-1]
        user_id = message.from_user.id if message.from_user else 0

        filename = f"photo_{photo.file_id[:8]}.jpg"

        logger.info(
            "normalizer.processing_photo",
            user_id=user_id,
            width=photo.width,
            height=photo.height,
            file_size=photo.file_size,
        )

        # Download and cache
        photo_bytes = await self._download_file(message,
                                                photo.file_id,
                                                filename=filename)

        # Detect MIME
        mime_type = detect_mime_type(
            filename=filename,
            file_bytes=photo_bytes,
            declared_mime="image/jpeg",
        )

        # Upload to Files API
        claude_file_id = await upload_to_files_api(
            file_bytes=photo_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        logger.info(
            "normalizer.photo_uploaded",
            user_id=user_id,
            filename=filename,
            claude_file_id=claude_file_id,
            size_bytes=len(photo_bytes),
        )

        return [
            UploadedFile(
                claude_file_id=claude_file_id,
                telegram_file_id=photo.file_id,
                telegram_file_unique_id=photo.file_unique_id,
                file_type=MediaType.IMAGE,
                filename=filename,
                mime_type=mime_type,
                size_bytes=photo.file_size or len(photo_bytes),
                metadata={
                    "width": photo.width,
                    "height": photo.height,
                },
            )
        ]

    async def _process_document(self,
                                message: types.Message) -> list[UploadedFile]:
        """Process document by uploading to Files API.

        Args:
            message: Telegram message with document.

        Returns:
            List with single UploadedFile.
        """
        document = message.document
        user_id = message.from_user.id if message.from_user else 0

        filename = document.file_name or f"document_{document.file_id[:8]}"

        logger.info(
            "normalizer.processing_document",
            user_id=user_id,
            filename=filename,
            mime_type=document.mime_type,
            file_size=document.file_size,
        )

        # Download and cache
        doc_bytes = await self._download_file(message,
                                              document.file_id,
                                              filename=filename)

        # Detect MIME
        mime_type = detect_mime_type(
            filename=filename,
            file_bytes=doc_bytes,
            declared_mime=document.mime_type,
        )

        # Determine file type from MIME
        if is_pdf_mime(mime_type):
            file_type = MediaType.PDF
        elif is_image_mime(mime_type):
            file_type = MediaType.IMAGE
        elif is_audio_mime(mime_type):
            file_type = MediaType.AUDIO
        elif is_video_mime(mime_type):
            file_type = MediaType.VIDEO
        else:
            file_type = MediaType.DOCUMENT

        # Upload to Files API
        claude_file_id = await upload_to_files_api(
            file_bytes=doc_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        logger.info(
            "normalizer.document_uploaded",
            user_id=user_id,
            filename=filename,
            claude_file_id=claude_file_id,
            file_type=file_type.value,
            size_bytes=len(doc_bytes),
        )

        return [
            UploadedFile(
                claude_file_id=claude_file_id,
                telegram_file_id=document.file_id,
                telegram_file_unique_id=document.file_unique_id,
                file_type=file_type,
                filename=filename,
                mime_type=mime_type,
                size_bytes=document.file_size or len(doc_bytes),
                metadata={},
            )
        ]


# Global singleton instance
_normalizer: Optional[MessageNormalizer] = None


def get_normalizer() -> MessageNormalizer:
    """Get the global normalizer instance.

    Returns:
        MessageNormalizer singleton.
    """
    global _normalizer  # pylint: disable=global-statement
    if _normalizer is None:
        _normalizer = MessageNormalizer()
    return _normalizer
