"""Universal Chat Action System.

Provides automatic, context-aware Telegram status indicators.
Uses existing MediaType/FileType enums for type-safe action resolution.

Quick Start (New API):
    from telegram.chat_action import ActionManager
    from telegram.pipeline.models import MediaType

    # Get or create manager for this chat
    manager = ActionManager.get(bot, chat_id, thread_id)

    # Use semantic scopes with enum types
    async with manager.generating():
        await stream_response()  # Shows "typing"

        async with manager.uploading(file_type=MediaType.IMAGE):
            await send_photo()  # Shows "upload_photo"

    # Or with FileType from database layer
    from db.models.user_file import FileType
    async with manager.uploading(file_type=FileType.VIDEO):
        await send_video()  # Shows "upload_video"

    # MIME fallback when enum not available
    async with manager.uploading(mime_type="audio/mpeg"):
        await send_audio()  # Auto-converts → "upload_voice"

Legacy API (still available for backwards compatibility):
    from telegram.chat_action import send_action, continuous_action

    await send_action(bot, chat_id, "typing", thread_id)

    async with continuous_action(bot, chat_id, "upload_photo", thread_id):
        await upload_file()
"""

from db.models.user_file import FileType
# Legacy API (backwards compatible)
from telegram.chat_action.legacy import ChatActionContext
from telegram.chat_action.legacy import continuous_action
from telegram.chat_action.legacy import send_action
from telegram.chat_action.manager import ChatActionManager as ActionManager
from telegram.chat_action.resolver import resolve_action
from telegram.chat_action.scope import ActionScope
# New API
from telegram.chat_action.types import ActionPhase
from telegram.chat_action.types import ActionPriority
from telegram.chat_action.types import ChatAction
# Re-export file type enums for convenience
from telegram.pipeline.models import MediaType

__all__ = [
    # New API
    "ActionManager",
    "ActionPhase",
    "ActionPriority",
    "ActionScope",
    "ChatAction",
    "resolve_action",
    # File types (convenience re-export)
    "MediaType",
    "FileType",
    # Legacy API
    "send_action",
    "continuous_action",
    "ChatActionContext",
]
