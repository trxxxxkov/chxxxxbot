"""Data structures for unified message pipeline.

This module defines the core data structures for the unified message processing
pipeline (Architecture Refactoring):

- ProcessedMessage: Universal container for all message types
- UploadedFile: File ready for Claude API (already uploaded)
- TranscriptInfo: Transcription result from Whisper
- ReplyContext: Reply/forward/quote context
- MessageMetadata: Chat/user/message metadata

Key invariant: All files are uploaded BEFORE entering the queue,
eliminating race conditions at the design level.

NO __init__.py - use direct import:
    from telegram.pipeline.models import ProcessedMessage, UploadedFile
"""

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import types


class MediaType(str, Enum):
    """Media type classification for pipeline processing.

    Determines processing strategy:
    - VOICE, VIDEO_NOTE: Auto-transcribe with Whisper (user speech)
    - AUDIO, VIDEO: Upload to Files API, transcribe on demand
    - IMAGE, DOCUMENT, PDF: Upload to Files API for Claude vision/analysis

    This enum is specific to the pipeline and may differ from db.models.user_file.
    """

    VOICE = "voice"  # Voice message (OGG/OPUS) -> auto-transcribe
    VIDEO_NOTE = "video_note"  # Round video -> auto-transcribe
    AUDIO = "audio"  # Audio file -> Files API (on-demand transcribe)
    VIDEO = "video"  # Video file -> Files API (on-demand transcribe)
    IMAGE = "image"  # Photo -> Files API (vision)
    DOCUMENT = "document"  # Document -> Files API
    PDF = "pdf"  # PDF -> Files API (PDF parser)


@dataclass
class TranscriptInfo:
    """Transcription result from Whisper API.

    Contains the transcript and metadata from speech-to-text processing.
    Used for voice messages and video notes.

    Attributes:
        text: Transcribed text content.
        duration_seconds: Duration of the audio in seconds.
        detected_language: Language detected by Whisper (ISO code).
        cost_usd: Cost of the Whisper API call in USD.
    """

    text: str
    duration_seconds: float
    detected_language: str
    cost_usd: float


@dataclass
class UploadedFile:
    """File uploaded to Claude Files API, ready for use.

    Key invariant: This represents a file that has ALREADY been uploaded
    to the Files API. The claude_file_id is guaranteed to be valid.

    Attributes:
        claude_file_id: Files API ID (ready to use in message content).
        telegram_file_id: Telegram file ID (for DB reference).
        telegram_file_unique_id: Telegram unique file ID (for dedup).
        file_type: Media type classification.
        filename: Original or generated filename.
        mime_type: Detected MIME type.
        size_bytes: File size in bytes.
        metadata: Additional metadata (width/height, duration, etc).
    """

    claude_file_id: str
    telegram_file_id: str
    telegram_file_unique_id: str
    file_type: MediaType
    filename: str
    mime_type: str
    size_bytes: int
    metadata: dict = field(default_factory=dict)


@dataclass
class ReplyContext:
    """Context from reply_to_message, forward, or quote.

    Extracted context that should be included in the Claude request
    to provide conversation continuity.

    Attributes:
        original_text: Text from the original message (if available).
        original_sender: Display name of original sender.
        original_message_id: Message ID being replied to.
        is_forward: Whether this is a forwarded message.
        is_quote: Whether this is a quoted reply (Bot API 9.3).
        quote_text: Specific quoted text (if is_quote).
    """

    original_text: Optional[str] = None
    original_sender: Optional[str] = None
    original_message_id: Optional[int] = None
    is_forward: bool = False
    is_quote: bool = False
    quote_text: Optional[str] = None


@dataclass
class MessageMetadata:
    """Metadata extracted from Telegram message.

    Contains all identifying information needed for DB operations
    and logging without needing access to the original message.

    Attributes:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        message_id: Telegram message ID.
        message_thread_id: Telegram thread ID (for forums/topics).
        chat_type: Chat type (private, group, supergroup, channel).
        date: Message timestamp.
        is_topic_message: Whether in a forum topic.
        username: User's username (optional).
        first_name: User's first name.
        last_name: User's last name (optional).
        is_premium: Whether user has Telegram Premium.
    """

    chat_id: int
    user_id: int
    message_id: int
    message_thread_id: Optional[int]
    chat_type: str
    date: datetime
    is_topic_message: bool = False
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_premium: bool = False


@dataclass
class ProcessedMessage:
    """Universal container for all message types.

    This is the core data structure of the unified pipeline.
    All processing (download, upload, transcription) is complete
    before this object is created.

    Invariants:
    - All files in `files` are ALREADY uploaded (claude_file_id valid)
    - All transcriptions are complete (transcript populated)
    - All context is extracted (reply_context populated)
    - No network operations needed after creation

    Attributes:
        text: Text content or caption (may be None for media-only).
        files: List of uploaded files (ready for Claude API).
        transcript: Transcription info (for voice/video_note).
        reply_context: Context from reply/forward/quote.
        metadata: Message metadata (chat_id, user_id, etc).
        original_message: Original aiogram Message (for reference only).
        transcription_charged: Whether transcription cost was already charged.
    """

    text: Optional[str]
    metadata: MessageMetadata
    original_message: 'types.Message'
    files: list[UploadedFile] = field(default_factory=list)
    transcript: Optional[TranscriptInfo] = None
    reply_context: Optional[ReplyContext] = None
    transcription_charged: bool = False

    @property
    def has_media(self) -> bool:
        """Check if message has any media content.

        Returns:
            True if message has files or transcript.
        """
        return bool(self.files) or self.transcript is not None

    @property
    def has_files(self) -> bool:
        """Check if message has uploaded files.

        Returns:
            True if message has files ready for Claude API.
        """
        return bool(self.files)

    @property
    def has_transcript(self) -> bool:
        """Check if message has a transcript (voice/video_note).

        Returns:
            True if message was transcribed.
        """
        return self.transcript is not None

    def get_text_for_db(self) -> str:
        """Get text content suitable for database storage.

        For transcripts, adds a prefix indicating voice message.
        For regular text, returns as-is.

        Returns:
            Text content for DB storage.
        """
        if self.transcript:
            duration = int(self.transcript.duration_seconds)
            return f"[VOICE MESSAGE - {duration}s]: {self.transcript.text}"
        return self.text or ""

    def get_text_for_claude(self) -> str:
        """Get text content for Claude API.

        Same as get_text_for_db but may be extended in future
        for Claude-specific formatting.

        Returns:
            Text content for Claude API.
        """
        return self.get_text_for_db()

    def get_file_mentions(self) -> str:
        """Generate file mentions string for context.

        Used to inform Claude about available files in the message.

        Returns:
            Formatted string listing available files.
        """
        if not self.files:
            return ""

        mentions = []
        for f in self.files:
            size_str = _format_size(f.size_bytes)
            mentions.append(f"- {f.filename} ({f.mime_type}, {size_str}) "
                            f"[Files API: {f.claude_file_id}]")

        return "Available files:\n" + "\n".join(mentions)


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted size string (e.g., '1.5 MB').
    """
    size: float = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
