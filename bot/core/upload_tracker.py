"""Pending upload tracker for message queue synchronization.

This module tracks in-flight file uploads to ensure the message queue
waits for uploads to complete before processing batches.

Problem solved:
- Photo+caption arrives → handler starts downloading/uploading (blocking)
- Meanwhile, text message arrives and starts 200ms timer
- Timer expires → batch processes before photo upload finishes
- Result: text processes alone, photo processes in separate batch

Solution:
- Track pending uploads per chat (by chat_id, available before upload)
- Message queue waits for uploads before processing

NO __init__.py - use direct import:
    from core.upload_tracker import get_upload_tracker
"""

import asyncio
from typing import Dict

from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Default timeout for waiting on uploads (seconds)
DEFAULT_UPLOAD_TIMEOUT = 10.0


class PendingUploadTracker:
    """Tracks pending file uploads per chat.

    Uses chat_id for tracking because it's available before the upload
    starts (unlike thread_id which requires database query).

    Thread-safe tracker for coordinating file uploads with message queue.

    Usage pattern:
    1. Before upload: await tracker.start_upload(chat_id)
    2. After upload (success or fail): await tracker.finish_upload(chat_id)
    3. In queue: await tracker.wait_for_uploads(chat_id)
    """

    def __init__(self) -> None:
        """Initialize the tracker."""
        self._pending: Dict[int, asyncio.Event] = {}  # chat_id -> event
        self._counts: Dict[int, int] = {}  # chat_id -> pending count
        self._lock = asyncio.Lock()

        logger.debug("upload_tracker.initialized")

    async def start_upload(self, chat_id: int) -> None:
        """Mark an upload as starting.

        Call this BEFORE starting any async download/upload work.
        Must be paired with finish_upload().

        Args:
            chat_id: Telegram chat ID.
        """
        async with self._lock:
            self._counts[chat_id] = self._counts.get(chat_id, 0) + 1

            if chat_id not in self._pending:
                self._pending[chat_id] = asyncio.Event()
                # Event starts unset (uploads are pending)

            logger.debug("upload_tracker.upload_started",
                         chat_id=chat_id,
                         pending_count=self._counts[chat_id])

    async def finish_upload(self, chat_id: int) -> None:
        """Mark an upload as complete.

        Call this AFTER upload finishes (success or failure).
        Must be called in finally block to ensure cleanup.

        Args:
            chat_id: Telegram chat ID.
        """
        async with self._lock:
            self._counts[chat_id] = max(0, self._counts.get(chat_id, 0) - 1)

            if self._counts[chat_id] == 0:
                if chat_id in self._pending:
                    self._pending[chat_id].set()
                    logger.debug("upload_tracker.all_uploads_complete",
                                 chat_id=chat_id)
            else:
                logger.debug("upload_tracker.upload_finished",
                             chat_id=chat_id,
                             remaining=self._counts[chat_id])

    async def wait_for_uploads(
        self,
        chat_id: int,
        timeout: float = DEFAULT_UPLOAD_TIMEOUT,
    ) -> bool:
        """Wait for all pending uploads to complete.

        Call this before processing message batch.

        Args:
            chat_id: Telegram chat ID.
            timeout: Maximum time to wait in seconds.

        Returns:
            True if all uploads completed, False if timed out.
        """
        event = self._pending.get(chat_id)
        count = self._counts.get(chat_id, 0)

        # No pending uploads - return immediately
        if not event or count == 0:
            return True

        logger.debug("upload_tracker.waiting",
                     chat_id=chat_id,
                     pending_count=count,
                     timeout=timeout)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            logger.debug("upload_tracker.wait_complete", chat_id=chat_id)
            return True

        except asyncio.TimeoutError:
            logger.warning("upload_tracker.timeout",
                           chat_id=chat_id,
                           pending=self._counts.get(chat_id, 0),
                           timeout=timeout)
            return False

    def has_pending_uploads(self, chat_id: int) -> bool:
        """Check if chat has pending uploads.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            True if there are pending uploads.
        """
        return self._counts.get(chat_id, 0) > 0

    def get_pending_count(self, chat_id: int) -> int:
        """Get number of pending uploads for chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Number of pending uploads.
        """
        return self._counts.get(chat_id, 0)

    async def reset(self, chat_id: int) -> None:
        """Reset tracker state for a chat.

        Use this for cleanup or error recovery.

        Args:
            chat_id: Telegram chat ID.
        """
        async with self._lock:
            self._counts.pop(chat_id, None)
            event = self._pending.pop(chat_id, None)
            if event:
                event.set()  # Unblock any waiters

            logger.debug("upload_tracker.reset", chat_id=chat_id)


# Global singleton instance
_upload_tracker: PendingUploadTracker | None = None


def get_upload_tracker() -> PendingUploadTracker:
    """Get the global upload tracker instance.

    Returns:
        The singleton PendingUploadTracker.
    """
    global _upload_tracker
    if _upload_tracker is None:
        _upload_tracker = PendingUploadTracker()
    return _upload_tracker
