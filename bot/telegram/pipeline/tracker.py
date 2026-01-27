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


class MediaGroupTracker:
    """Track media groups to wait for all files before processing.

    Telegram sends media groups (multiple photos/videos) as separate messages
    with the same media_group_id. Files arrive ~50-200ms apart. This tracker
    waits until no new files arrive for a "quiet period", indicating the
    group is complete.

    Usage:
        tracker = get_media_group_tracker()

        # In handler, when message has media_group_id:
        tracker.register(media_group_id)

        # In queue, before processing:
        await tracker.wait_for_complete(media_group_id, quiet_period=0.3)
    """

    def __init__(self, quiet_period: float = 0.3) -> None:
        """Initialize tracker.

        Args:
            quiet_period: Seconds of silence before group is considered complete.
        """
        self._groups: Dict[str, float] = {}  # media_group_id -> last_seen_time
        self._lock = asyncio.Lock()
        self._quiet_period = quiet_period
        logger.info("media_group_tracker.initialized",
                    quiet_period=quiet_period)

    async def register(self, media_group_id: str) -> None:
        """Register a message as part of media group.

        Call this when a message with media_group_id arrives.

        Args:
            media_group_id: Telegram media group ID.
        """
        import time
        async with self._lock:
            self._groups[media_group_id] = time.monotonic()
            logger.debug(
                "media_group_tracker.registered",
                media_group_id=media_group_id,
            )

    async def wait_for_complete(
        self,
        media_group_id: str,
        quiet_period: float | None = None,
        max_wait: float = 5.0,
    ) -> bool:
        """Wait for media group to be complete.

        Waits until no new messages with this media_group_id arrive
        for quiet_period seconds.

        Args:
            media_group_id: Telegram media group ID.
            quiet_period: Override default quiet period (seconds).
            max_wait: Maximum total wait time (seconds).

        Returns:
            True if completed normally, False if max_wait exceeded.
        """
        import time

        if quiet_period is None:
            quiet_period = self._quiet_period

        start_time = time.monotonic()
        check_interval = 0.05  # 50ms

        logger.info(
            "media_group_tracker.waiting",
            media_group_id=media_group_id,
            quiet_period=quiet_period,
            max_wait=max_wait,
        )

        while True:
            async with self._lock:
                last_seen = self._groups.get(media_group_id)

                if last_seen is None:
                    # Group not registered, nothing to wait for
                    return True

                elapsed_since_last = time.monotonic() - last_seen
                total_elapsed = time.monotonic() - start_time

                if elapsed_since_last >= quiet_period:
                    # No new messages for quiet_period - group is complete
                    logger.info(
                        "media_group_tracker.complete",
                        media_group_id=media_group_id,
                        elapsed_since_last=round(elapsed_since_last, 3),
                        total_elapsed=round(total_elapsed, 3),
                    )
                    # Cleanup
                    del self._groups[media_group_id]
                    return True

                if total_elapsed >= max_wait:
                    # Max wait exceeded
                    logger.warning(
                        "media_group_tracker.timeout",
                        media_group_id=media_group_id,
                        total_elapsed=round(total_elapsed, 3),
                        max_wait=max_wait,
                    )
                    # Cleanup
                    del self._groups[media_group_id]
                    return False

            # Wait and check again
            await asyncio.sleep(check_interval)

    def get_stats(self) -> dict:
        """Get tracker statistics.

        Returns:
            Dict with tracker stats.
        """
        return {
            "active_groups": len(self._groups),
        }


# Global singletons
_tracker: NormalizationTracker | None = None
_media_group_tracker: MediaGroupTracker | None = None


def get_tracker() -> NormalizationTracker:
    """Get or create the global normalization tracker instance.

    Returns:
        NormalizationTracker singleton.
    """
    global _tracker  # pylint: disable=global-statement
    if _tracker is None:
        _tracker = NormalizationTracker()
    return _tracker


def get_media_group_tracker() -> MediaGroupTracker:
    """Get or create the global media group tracker instance.

    Returns:
        MediaGroupTracker singleton.
    """
    global _media_group_tracker  # pylint: disable=global-statement
    if _media_group_tracker is None:
        _media_group_tracker = MediaGroupTracker()
    return _media_group_tracker
