"""Action scope context manager for universal chat action system.

Provides ActionScope class that automatically manages chat action lifecycle.

NO __init__.py - use direct import:
    from telegram.chat_action.scope import ActionScope
"""

from typing import Optional, TYPE_CHECKING

from .types import ActionPhase
from .types import ActionPriority
from .types import FileTypeHint

if TYPE_CHECKING:
    from .manager import ChatActionManager


class ActionScope:
    """A scoped action that automatically manages its lifecycle.

    Scopes are stackable - inner scope temporarily overrides outer.
    When inner scope exits, outer scope's action resumes.

    Usage:
        async with ActionScope(manager, ActionPhase.GENERATING):
            await generate_text()  # Shows "typing"

            async with ActionScope(manager, ActionPhase.UPLOADING, MediaType.IMAGE):
                await send_photo()  # Shows "upload_photo"

            # Back to "typing" automatically
    """

    def __init__(
        self,
        manager: "ChatActionManager",
        phase: ActionPhase,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
        priority: ActionPriority = ActionPriority.NORMAL,
    ):
        """Initialize action scope.

        Args:
            manager: ChatActionManager instance.
            phase: What the bot is doing (GENERATING, UPLOADING, etc).
            file_type: MediaType or FileType enum (preferred).
            mime_type: Optional MIME string (fallback if file_type is None).
            priority: Scope priority for concurrent operations.
        """
        self.manager = manager
        self.phase = phase
        self.file_type = file_type
        self.mime_type = mime_type
        self.priority = priority
        self._scope_id: Optional[str] = None

    async def __aenter__(self) -> "ActionScope":
        """Enter scope and start action loop if needed."""
        self._scope_id = await self.manager.push_scope(
            phase=self.phase,
            file_type=self.file_type,
            mime_type=self.mime_type,
            priority=self.priority,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit scope and restore previous action."""
        if self._scope_id:
            await self.manager.pop_scope(self._scope_id)
