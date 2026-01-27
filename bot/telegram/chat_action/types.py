"""Type definitions for universal chat action system.

This module defines the core types and resolution table for mapping
operation phases and file types to Telegram chat actions.

NO __init__.py - use direct import:
    from telegram.chat_action.types import ActionPhase, ActionPriority
"""

from enum import auto
from enum import Enum
from typing import Literal, Union

from db.models.user_file import FileType
# Import existing file type enums from project
from telegram.pipeline.models import MediaType

# Telegram chat action type (from aiogram)
ChatAction = Literal[
    "typing",
    "upload_photo",
    "upload_document",
    "upload_video",
    "upload_voice",
    "record_voice",
    "record_video",
    "record_video_note",
    "upload_video_note",
    "choose_sticker",
    "find_location",
]


class ActionPhase(Enum):
    """Semantic operation phase (what bot is DOING).

    This represents the PHASE of operation, not the file type.
    File type is determined separately via MediaType/FileType.
    """

    IDLE = auto()  # No action needed
    GENERATING = auto()  # Thinking/writing text (typing)
    PROCESSING = auto()  # Processing input - transcription, OCR (record_*)
    UPLOADING = auto()  # Sending file to user (upload_*)
    DOWNLOADING = auto()  # Receiving file from user (record_* or upload_*)
    SEARCHING = auto()  # Web search / location lookup


class ActionPriority(Enum):
    """Priority for concurrent operations.

    Higher priority actions override lower when multiple scopes are active.
    """

    LOW = 1  # Background processing
    NORMAL = 2  # Standard generation
    HIGH = 3  # File transfer (user waiting to see file)


# Unified file type alias - accepts both pipeline and database enums
FileTypeHint = Union[MediaType, FileType, None]

# Resolution table: (ActionPhase, FileTypeHint) → ChatAction string
# None as file type = default for that phase
ACTION_RESOLUTION_TABLE: dict[tuple, ChatAction] = {
    # === GENERATING: Always typing (no file context) ===
    (ActionPhase.GENERATING, None):
        "typing",
    # === UPLOADING: Depends on file type (sending TO user) ===
    # MediaType variants (pipeline layer)
    (ActionPhase.UPLOADING, MediaType.IMAGE):
        "upload_photo",
    (ActionPhase.UPLOADING, MediaType.VIDEO):
        "upload_video",
    (ActionPhase.UPLOADING, MediaType.VIDEO_NOTE):
        "upload_video_note",
    (ActionPhase.UPLOADING, MediaType.AUDIO):
        "upload_voice",
    (ActionPhase.UPLOADING, MediaType.VOICE):
        "upload_voice",
    (ActionPhase.UPLOADING, MediaType.DOCUMENT):
        "upload_document",
    (ActionPhase.UPLOADING, MediaType.PDF):
        "upload_document",
    # FileType variants (database layer)
    (ActionPhase.UPLOADING, FileType.IMAGE):
        "upload_photo",
    (ActionPhase.UPLOADING, FileType.VIDEO):
        "upload_video",
    (ActionPhase.UPLOADING, FileType.AUDIO):
        "upload_voice",
    (ActionPhase.UPLOADING, FileType.VOICE):
        "upload_voice",
    (ActionPhase.UPLOADING, FileType.DOCUMENT):
        "upload_document",
    (ActionPhase.UPLOADING, FileType.PDF):
        "upload_document",
    (ActionPhase.UPLOADING, FileType.GENERATED):
        "upload_document",
    # Default for unknown file type
    (ActionPhase.UPLOADING, None):
        "upload_document",
    # === DOWNLOADING: Receiving FROM user ===
    # Voice/video notes show "recording" indicator
    (ActionPhase.DOWNLOADING, MediaType.VOICE):
        "record_voice",
    (ActionPhase.DOWNLOADING, MediaType.VIDEO_NOTE):
        "record_video",
    # Other media shows "uploading" (bot is receiving/uploading to API)
    (ActionPhase.DOWNLOADING, MediaType.AUDIO):
        "upload_voice",
    (ActionPhase.DOWNLOADING, MediaType.VIDEO):
        "upload_video",
    (ActionPhase.DOWNLOADING, MediaType.IMAGE):
        "upload_photo",
    (ActionPhase.DOWNLOADING, MediaType.DOCUMENT):
        "upload_document",
    (ActionPhase.DOWNLOADING, MediaType.PDF):
        "upload_document",
    (ActionPhase.DOWNLOADING, None):
        "typing",
    # === PROCESSING: Transcription, OCR, analysis ===
    (ActionPhase.PROCESSING, MediaType.VOICE):
        "record_voice",
    (ActionPhase.PROCESSING, MediaType.VIDEO_NOTE):
        "record_video",
    (ActionPhase.PROCESSING, MediaType.AUDIO):
        "record_voice",
    (ActionPhase.PROCESSING, MediaType.VIDEO):
        "record_video",
    (ActionPhase.PROCESSING, None):
        "typing",
    # === SEARCHING: Location or web search ===
    (ActionPhase.SEARCHING, None):
        "typing",
}
