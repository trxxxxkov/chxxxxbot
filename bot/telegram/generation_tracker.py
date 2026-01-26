"""Generation tracking for cancellation support.

This module provides a singleton tracker for active Claude generations,
allowing users to stop generation mid-stream via inline keyboard buttons.

NO __init__.py - use direct import:
    from telegram.generation_tracker import generation_tracker
    from telegram.generation_tracker import GenerationContext
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from utils.structured_logging import get_logger

logger = get_logger(__name__)


class GenerationTracker:
    """Tracks active generations for cancellation support.

    Maintains a mapping of (chat_id, user_id, thread_id) to asyncio.Event objects.
    When a user requests cancellation, the corresponding event is set,
    and the streaming loop can check this event to stop early.

    Only one active generation per user per thread is tracked.
    Starting a new generation overwrites any previous one.

    Example:
        # In streaming handler:
        cancel_event = generation_tracker.start(chat_id, user_id, thread_id)
        try:
            async for event in stream:
                if cancel_event.is_set():
                    break
                # process event...
        finally:
            generation_tracker.cleanup(chat_id, user_id, thread_id)

        # In callback handler:
        if generation_tracker.cancel(chat_id, user_id, thread_id):
            await callback.answer("Stopping...")
    """

    def __init__(self) -> None:
        """Initialize tracker."""
        self._active: dict[tuple[int, int, int | None], asyncio.Event] = {}
        self._lock = asyncio.Lock()
        # Note: Don't log here - singleton is created at module import time,
        # before structlog is configured, which causes non-JSON log output.

    async def start(
        self,
        chat_id: int,
        user_id: int,
        thread_id: int | None = None,
    ) -> asyncio.Event:
        """Start tracking a new generation.

        Creates a new asyncio.Event for cancellation signaling.
        If a generation is already active for this user/thread, it's replaced.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            thread_id: Telegram thread/topic ID (None for main chat).

        Returns:
            asyncio.Event that will be set when cancellation is requested.
        """
        async with self._lock:
            key = (chat_id, user_id, thread_id)

            # Clean up any existing generation (shouldn't happen normally)
            if key in self._active:
                logger.warning(
                    "generation_tracker.overwriting_active",
                    chat_id=chat_id,
                    user_id=user_id,
                    thread_id=thread_id,
                )

            event = asyncio.Event()
            self._active[key] = event

            logger.debug(
                "generation_tracker.started",
                chat_id=chat_id,
                user_id=user_id,
                thread_id=thread_id,
                active_count=len(self._active),
            )

            return event

    async def cancel(
        self,
        chat_id: int,
        user_id: int,
        thread_id: int | None = None,
    ) -> bool:
        """Request cancellation of an active generation.

        Sets the cancellation event if found.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            thread_id: Telegram thread/topic ID (None for main chat).

        Returns:
            True if generation was found and cancelled, False otherwise.
        """
        async with self._lock:
            key = (chat_id, user_id, thread_id)

            if key not in self._active:
                logger.debug(
                    "generation_tracker.cancel_not_found",
                    chat_id=chat_id,
                    user_id=user_id,
                    thread_id=thread_id,
                )
                return False

            self._active[key].set()

            logger.info(
                "generation_tracker.cancelled",
                chat_id=chat_id,
                user_id=user_id,
                thread_id=thread_id,
            )

            return True

    async def cleanup(
        self,
        chat_id: int,
        user_id: int,
        thread_id: int | None = None,
    ) -> None:
        """Remove generation from tracking after completion.

        Safe to call even if no generation is tracked.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            thread_id: Telegram thread/topic ID (None for main chat).
        """
        async with self._lock:
            key = (chat_id, user_id, thread_id)
            removed = self._active.pop(key, None)

            if removed:
                logger.debug(
                    "generation_tracker.cleaned_up",
                    chat_id=chat_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    was_cancelled=removed.is_set(),
                    active_count=len(self._active),
                )

    def is_active(
        self,
        chat_id: int,
        user_id: int,
        thread_id: int | None = None,
    ) -> bool:
        """Check if a generation is currently active.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            thread_id: Telegram thread/topic ID (None for main chat).

        Returns:
            True if generation is active (and not yet cancelled).
        """
        key = (chat_id, user_id, thread_id)
        event = self._active.get(key)
        return event is not None and not event.is_set()

    def get_active_count(self) -> int:
        """Get count of active generations (for monitoring).

        Returns:
            Number of currently tracked generations.
        """
        return len(self._active)


# Singleton instance
generation_tracker = GenerationTracker()


@asynccontextmanager
async def generation_context(
    chat_id: int,
    user_id: int,
    thread_id: int | None = None,
) -> AsyncIterator[asyncio.Event]:
    """Context manager for generation tracking.

    Handles starting and cleanup of generation tracking.
    User can stop generation via /stop command or by sending a new message
    in the same thread.

    Example:
        async with generation_context(chat_id, user_id, thread_id) as cancel_event:
            async for event in stream:
                if cancel_event.is_set():
                    break
                # process event...

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        thread_id: Telegram thread/topic ID (None for main chat).

    Yields:
        asyncio.Event that is set when user requests cancellation.
    """
    # Start tracking
    cancel_event = await generation_tracker.start(chat_id, user_id, thread_id)

    try:
        yield cancel_event
    finally:
        # Cleanup generation tracking
        await generation_tracker.cleanup(chat_id, user_id, thread_id)
