"""Normalization tracker for unified pipeline.

This module tracks messages that are currently being normalized
(download, upload, transcription) per chat. The queue uses this
to wait for pending messages before processing a batch.

This solves the race condition where:
1. Text message arrives, quickly normalized, added to queue
2. Photo message arrives, starts normalizing (slow - download+upload)
3. Text batch timer fires BEFORE photo finishes
4. Result: Text and photo processed in separate batches

With the tracker:
1. Both messages register as "pending" immediately
2. Queue waits for all pending messages before processing
3. Result: Both messages processed together

NO __init__.py - use direct import:
    from telegram.pipeline.tracker import get_tracker
"""

import asyncio
from typing import Dict, Set

from utils.structured_logging import get_logger

logger = get_logger(__name__)


class NormalizationTracker:
    """Track messages currently being normalized per chat.

    Each chat has a set of message_ids being processed and an event
    that signals when all messages are done.

    Usage:
        tracker = get_tracker()

        # In handler, before normalizing:
        tracker.start(chat_id, message_id)

        try:
            processed = await normalizer.normalize(message)
            await queue.add(thread_id, processed)
        finally:
            tracker.finish(chat_id, message_id)

        # In queue, before processing batch:
        await tracker.wait_for_chat(chat_id, timeout=3.0)
    """

    def __init__(self) -> None:
        """Initialize tracker."""
        self._pending: Dict[int, Set[int]] = {}  # chat_id -> set of message_ids
        self._events: Dict[int, asyncio.Event] = {}  # chat_id -> event
        self._lock = asyncio.Lock()
        logger.info("normalization_tracker.initialized")

    async def start(self, chat_id: int, message_id: int) -> None:
        """Mark message as being normalized.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
        """
        async with self._lock:
            if chat_id not in self._pending:
                self._pending[chat_id] = set()
                self._events[chat_id] = asyncio.Event()

            self._pending[chat_id].add(message_id)
            # Clear event since there are pending messages
            self._events[chat_id].clear()

            logger.debug(
                "normalization_tracker.start",
                chat_id=chat_id,
                message_id=message_id,
                pending_count=len(self._pending[chat_id]),
            )

    async def finish(self, chat_id: int, message_id: int) -> None:
        """Mark message as finished normalizing.

        Call this AFTER adding to queue, not after normalizing.
        This ensures the message is in the queue when wait returns.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
        """
        async with self._lock:
            if chat_id not in self._pending:
                return

            self._pending[chat_id].discard(message_id)
            pending_count = len(self._pending[chat_id])

            logger.debug(
                "normalization_tracker.finish",
                chat_id=chat_id,
                message_id=message_id,
                remaining=pending_count,
            )

            # If no more pending messages, set event
            if pending_count == 0:
                self._events[chat_id].set()
                # Clean up
                del self._pending[chat_id]
                # Keep event around briefly for any waiting tasks
                # It will be recreated if needed

    async def wait_for_chat(self, chat_id: int, timeout: float = 3.0) -> bool:
        """Wait for all pending normalizations in a chat.

        Args:
            chat_id: Telegram chat ID.
            timeout: Maximum seconds to wait.

        Returns:
            True if all pending completed, False if timeout.
        """
        # Quick check without lock
        if chat_id not in self._events:
            return True

        event = self._events.get(chat_id)
        if event is None:
            return True

        if event.is_set():
            return True

        # Check current pending count for logging
        pending_count = len(self._pending.get(chat_id, set()))
        if pending_count == 0:
            return True

        logger.info(
            "normalization_tracker.waiting",
            chat_id=chat_id,
            pending_count=pending_count,
            timeout=timeout,
        )

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            logger.info(
                "normalization_tracker.wait_complete",
                chat_id=chat_id,
            )
            return True

        except asyncio.TimeoutError:
            remaining = len(self._pending.get(chat_id, set()))
            logger.warning(
                "normalization_tracker.wait_timeout",
                chat_id=chat_id,
                remaining=remaining,
                timeout=timeout,
            )
            return False

    def has_pending(self, chat_id: int) -> bool:
        """Check if chat has pending normalizations.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            True if there are pending messages.
        """
        return len(self._pending.get(chat_id, set())) > 0

    def get_pending_count(self, chat_id: int) -> int:
        """Get count of pending messages for chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Number of pending messages.
        """
        return len(self._pending.get(chat_id, set()))

    def get_stats(self) -> dict:
        """Get tracker statistics.

        Returns:
            Dict with tracker stats.
        """
        return {
            "total_chats": len(self._pending),
            "total_pending": sum(len(msgs) for msgs in self._pending.values()),
        }


# Global singleton
_tracker: NormalizationTracker | None = None


def get_tracker() -> NormalizationTracker:
    """Get or create the global tracker instance.

    Returns:
        NormalizationTracker singleton.
    """
    global _tracker  # pylint: disable=global-statement
    if _tracker is None:
        _tracker = NormalizationTracker()
    return _tracker
