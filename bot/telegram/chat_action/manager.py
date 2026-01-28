"""Chat action manager for universal chat action system.

Provides ChatActionManager class - the main entry point for managing
Telegram chat actions (typing indicators, upload status, etc.).

NO __init__.py - use direct import:
    from telegram.chat_action.manager import ChatActionManager
"""

import asyncio
from typing import Optional, TYPE_CHECKING
import uuid
from weakref import WeakValueDictionary

from utils.structured_logging import get_logger

from .resolver import resolve_action
from .types import ActionPhase
from .types import ActionPriority
from .types import ChatAction
from .types import FileTypeHint

if TYPE_CHECKING:
    from aiogram import Bot

    from .scope import ActionScope

logger = get_logger(__name__)


class _ScopeEntry:
    """Internal representation of an active scope."""

    def __init__(
        self,
        scope_id: str,
        phase: ActionPhase,
        file_type: FileTypeHint,
        action: ChatAction,
        priority: ActionPriority,
    ):
        self.scope_id = scope_id
        self.phase = phase
        self.file_type = file_type
        self.action = action
        self.priority = priority


class ChatActionManager:
    """Centralized manager for chat actions in a single chat.

    Features:
    - Single action loop per chat (no duplicate API calls)
    - Priority-based action resolution (upload > typing)
    - Automatic file type based action selection (via MediaType/FileType enums)
    - Nested scope support for complex operations
    - MIME fallback when only string available

    Usage:
        manager = ChatActionManager.get(bot, chat_id, thread_id)

        async with manager.generating():
            # Shows "typing" indicator
            async with manager.uploading(file_type=MediaType.IMAGE):
                # Shows "upload_photo" indicator
            # Back to "typing"
    """

    # Global registry of active managers (weak refs for auto-cleanup)
    _registry: WeakValueDictionary[tuple,
                                   "ChatActionManager"] = WeakValueDictionary()

    # Refresh interval for action loop (Telegram clears after 5 seconds)
    ACTION_REFRESH_INTERVAL = 4.0

    @classmethod
    def get(
        cls,
        bot: "Bot",
        chat_id: int,
        thread_id: Optional[int] = None,
    ) -> "ChatActionManager":
        """Get or create manager for chat/thread.

        Args:
            bot: Telegram Bot instance.
            chat_id: Chat ID.
            thread_id: Forum topic ID (optional).

        Returns:
            ChatActionManager instance (reused if exists for same chat/thread).
        """
        key = (chat_id, thread_id)
        if key not in cls._registry:
            manager = cls(bot, chat_id, thread_id)
            cls._registry[key] = manager
        return cls._registry[key]

    def __init__(
        self,
        bot: "Bot",
        chat_id: int,
        thread_id: Optional[int] = None,
    ):
        """Initialize manager (prefer using .get() class method)."""
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self._scope_stack: list[_ScopeEntry] = []
        self._loop_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._current_action: Optional[ChatAction] = None

    # === High-level convenience methods ===

    def generating(self) -> "ActionScope":
        """Scope for text generation (typing indicator).

        Returns:
            ActionScope context manager.
        """
        from .scope import ActionScope
        return ActionScope(self, ActionPhase.GENERATING)

    def uploading(
        self,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
    ) -> "ActionScope":
        """Scope for file upload to user.

        Args:
            file_type: MediaType or FileType enum.
            mime_type: MIME string fallback if enum not available.

        Returns:
            ActionScope context manager.
        """
        from .scope import ActionScope
        return ActionScope(
            self,
            ActionPhase.UPLOADING,
            file_type=file_type,
            mime_type=mime_type,
            priority=ActionPriority.HIGH,
        )

    def downloading(
        self,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
    ) -> "ActionScope":
        """Scope for file download from user.

        Args:
            file_type: MediaType enum (preferred).
            mime_type: MIME string fallback.

        Returns:
            ActionScope context manager.
        """
        from .scope import ActionScope
        return ActionScope(
            self,
            ActionPhase.DOWNLOADING,
            file_type=file_type,
            mime_type=mime_type,
        )

    def processing(
        self,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
    ) -> "ActionScope":
        """Create scope for media processing operations.

        Used for transcription, OCR, and other processing tasks.

        Args:
            file_type: MediaType enum.
            mime_type: MIME string fallback.

        Returns:
            ActionScope context manager.
        """
        from .scope import ActionScope
        return ActionScope(
            self,
            ActionPhase.PROCESSING,
            file_type=file_type,
            mime_type=mime_type,
        )

    def searching(self) -> "ActionScope":
        """Scope for search operations.

        Returns:
            ActionScope context manager.
        """
        from .scope import ActionScope
        return ActionScope(self, ActionPhase.SEARCHING)

    # === Low-level scope management ===

    async def push_scope(
        self,
        phase: ActionPhase,
        file_type: FileTypeHint = None,
        mime_type: Optional[str] = None,
        priority: ActionPriority = ActionPriority.NORMAL,
    ) -> str:
        """Push new scope onto stack and update action loop.

        Args:
            phase: Operation phase.
            file_type: File type enum (optional).
            mime_type: MIME string fallback (optional).
            priority: Scope priority.

        Returns:
            Scope ID for later removal.
        """
        # Resolve action for this scope
        action = resolve_action(phase, file_type, mime_type=mime_type)
        scope_id = str(uuid.uuid4())

        entry = _ScopeEntry(
            scope_id=scope_id,
            phase=phase,
            file_type=file_type,
            action=action,
            priority=priority,
        )
        self._scope_stack.append(entry)

        logger.debug(
            "chat_action.scope_pushed",
            chat_id=self.chat_id,
            thread_id=self.thread_id,
            scope_id=scope_id,
            phase=phase.name,
            action=action,
            stack_size=len(self._scope_stack),
        )

        # Update the action loop
        await self._update_action()

        return scope_id

    async def pop_scope(self, scope_id: str) -> None:
        """Pop scope from stack and update action loop.

        Args:
            scope_id: Scope ID returned from push_scope.
        """
        # Find and remove scope by ID (handles out-of-order pops)
        for i, entry in enumerate(self._scope_stack):
            if entry.scope_id == scope_id:
                self._scope_stack.pop(i)
                logger.debug(
                    "chat_action.scope_popped",
                    chat_id=self.chat_id,
                    thread_id=self.thread_id,
                    scope_id=scope_id,
                    phase=entry.phase.name,
                    stack_size=len(self._scope_stack),
                )
                break

        # Update the action loop (may stop if no scopes left)
        await self._update_action()

    # === Action loop management ===

    def _get_active_action(self) -> Optional[ChatAction]:
        """Get the highest priority action from the scope stack."""
        if not self._scope_stack:
            return None

        # Find highest priority scope
        highest = max(self._scope_stack, key=lambda s: s.priority.value)
        return highest.action

    async def _update_action(self) -> None:
        """Update the action loop based on current scope stack."""
        new_action = self._get_active_action()

        if new_action is None:
            # No scopes - stop the loop
            await self._stop_loop()
            self._current_action = None
        elif new_action != self._current_action:
            # Action changed - restart loop with new action
            self._current_action = new_action
            await self._start_loop()

    async def _start_loop(self) -> None:
        """Start or restart the action refresh loop."""
        # Stop existing loop if running
        if self._loop_task and not self._loop_task.done():
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._loop_task, timeout=1.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    pass

        # Reset stop event and start new loop
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._action_loop())

    async def _stop_loop(self) -> None:
        """Stop the action refresh loop."""
        if self._loop_task and not self._loop_task.done():
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._loop_task, timeout=1.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    pass
            self._loop_task = None

    async def _action_loop(self) -> None:
        """Send chat action periodically until stopped."""
        while not self._stop_event.is_set():
            if self._current_action:
                await self._send_action(self._current_action)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.ACTION_REFRESH_INTERVAL,
                )
                break  # Event was set
            except asyncio.TimeoutError:
                pass  # Continue loop

    async def _send_action(self, action: ChatAction) -> bool:
        """Send a single chat action to Telegram.

        Args:
            action: Chat action to send.

        Returns:
            True on success, False on failure.
        """
        try:
            await self.bot.send_chat_action(
                chat_id=self.chat_id,
                action=action,
                message_thread_id=self.thread_id,
            )
            logger.debug(
                "chat_action.sent",
                chat_id=self.chat_id,
                thread_id=self.thread_id,
                action=action,
            )
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Don't fail the operation if chat action fails (cosmetic feature)
            logger.info(
                "chat_action.failed",
                chat_id=self.chat_id,
                thread_id=self.thread_id,
                action=action,
                error=str(e),
            )
            return False
