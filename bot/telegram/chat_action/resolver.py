"""Action resolver for universal chat action system.

Resolves (ActionPhase, FileType) pairs to Telegram ChatAction strings.

NO __init__.py - use direct import:
    from telegram.chat_action.resolver import resolve_action
"""

from typing import Optional

# Import CENTRALIZED conversion from core module (NO DUPLICATION!)
from core.mime_types import mime_to_media_type

from .types import ACTION_RESOLUTION_TABLE
from .types import ActionPhase
from .types import ChatAction
from .types import FileTypeHint


def resolve_action(
    phase: ActionPhase,
    file_type: FileTypeHint = None,
    *,
    mime_type: Optional[str] = None,
) -> ChatAction:
    """Resolve action phase + file type to Telegram ChatAction.

    Accepts multiple input types for flexibility:
    - MediaType enum (from pipeline) - PREFERRED
    - FileType enum (from database)
    - MIME string (auto-converted via core.mime_types.mime_to_media_type)

    Args:
        phase: What the bot is doing (GENERATING, UPLOADING, etc).
        file_type: MediaType, FileType enum, or None.
        mime_type: Optional MIME string (converted to MediaType if file_type is None).

    Returns:
        Telegram ChatAction string.

    Examples:
        >>> resolve_action(ActionPhase.GENERATING)
        'typing'
        >>> resolve_action(ActionPhase.UPLOADING, MediaType.IMAGE)
        'upload_photo'
        >>> resolve_action(ActionPhase.UPLOADING, FileType.VIDEO)
        'upload_video'
        >>> resolve_action(ActionPhase.UPLOADING, mime_type="image/png")
        'upload_photo'
        >>> resolve_action(ActionPhase.PROCESSING, MediaType.VOICE)
        'record_voice'
    """
    # Convert MIME to MediaType using EXISTING centralized function
    effective_file_type = file_type
    if effective_file_type is None and mime_type:
        effective_file_type = mime_to_media_type(mime_type)

    # Try exact match first
    key = (phase, effective_file_type)
    if key in ACTION_RESOLUTION_TABLE:
        return ACTION_RESOLUTION_TABLE[key]

    # Fallback to phase-only default
    default_key = (phase, None)
    return ACTION_RESOLUTION_TABLE.get(default_key, "typing")
