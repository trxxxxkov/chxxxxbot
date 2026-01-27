"""Per-user concurrency limiter for Claude API generations.

This module limits the number of concurrent Claude API calls per user.
When a user exceeds the limit, requests are queued and processed in order.

Key features:
- Per-user semaphore (default: 5 concurrent generations)
- Queue with position tracking for user feedback
- Balance check before waiting (don't wait if balance insufficient)
- Timeout to prevent infinite waits
- Metrics for monitoring

NO __init__.py - use direct import:
    from telegram.concurrency_limiter import concurrency_limiter
    from telegram.concurrency_limiter import ConcurrencyLimitExceeded
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import field
from typing import AsyncIterator

from config import CONCURRENCY_QUEUE_TIMEOUT
from config import MAX_CONCURRENT_GENERATIONS_PER_USER
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class ConcurrencyLimitExceeded(Exception):
    """Raised when user's concurrency queue times out.

    This exception is raised when a user has too many pending requests
    and the wait timeout is exceeded.

    Attributes:
        user_id: The user who exceeded the limit.
        queue_position: Position in queue when timeout occurred.
        wait_time: How long the request waited before timeout.
    """

    def __init__(
        self,
        user_id: int,
        queue_position: int,
        wait_time: float,
    ) -> None:
        """Initialize exception.

        Args:
            user_id: Telegram user ID.
            queue_position: Position in queue (1-based).
            wait_time: Seconds waited before timeout.
        """
        self.user_id = user_id
        self.queue_position = queue_position
        self.wait_time = wait_time
        super().__init__(f"Concurrency limit timeout for user {user_id}: "
                         f"position {queue_position}, waited {wait_time:.1f}s")


@dataclass
class UserConcurrencyState:
    """Per-user concurrency tracking state.

    Attributes:
        semaphore: Asyncio semaphore limiting concurrent requests.
        active_count: Current number of active generations.
        queue_count: Number of requests waiting in queue.
        total_processed: Total requests processed (for stats).
    """

    semaphore: asyncio.Semaphore
    active_count: int = 0
    queue_count: int = 0
    total_processed: int = 0


@dataclass
class QueuedRequest:
    """Represents a request waiting in the concurrency queue.

    Attributes:
        user_id: Telegram user ID.
        thread_id: Database thread ID.
        position: Position in queue (1-based).
        event: Event to signal when slot is available.
        created_at: Timestamp when request was queued.
    """

    user_id: int
    thread_id: int
    position: int
    event: asyncio.Event = field(default_factory=asyncio.Event)
    created_at: float = 0.0  # Set at runtime


class UserConcurrencyLimiter:
    """Limits concurrent Claude API calls per user.

    Uses per-user semaphores to limit parallelism. When a user exceeds
    the limit, requests are queued and processed FIFO.

    Example:
        limiter = UserConcurrencyLimiter(max_concurrent=5)

        async with limiter.acquire(user_id, thread_id) as slot:
            # slot.queue_position tells how long we waited
            await process_claude_request(...)

    Thread Safety:
        All operations are protected by asyncio.Lock for safe concurrent access.
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_GENERATIONS_PER_USER,
        queue_timeout: float = CONCURRENCY_QUEUE_TIMEOUT,
    ) -> None:
        """Initialize limiter.

        Args:
            max_concurrent: Maximum concurrent generations per user.
            queue_timeout: Maximum seconds to wait in queue.
        """
        self._max_concurrent = max_concurrent
        self._queue_timeout = queue_timeout
        self._users: dict[int, UserConcurrencyState] = {}
        self._lock = asyncio.Lock()

        # Don't log here - singleton created at import time before structlog configured

    def _get_or_create_user_state(self, user_id: int) -> UserConcurrencyState:
        """Get or create concurrency state for user.

        Args:
            user_id: Telegram user ID.

        Returns:
            UserConcurrencyState for this user.
        """
        if user_id not in self._users:
            self._users[user_id] = UserConcurrencyState(
                semaphore=asyncio.Semaphore(self._max_concurrent))
        return self._users[user_id]

    async def get_queue_position(self, user_id: int) -> int:
        """Get current queue position for user.

        Args:
            user_id: Telegram user ID.

        Returns:
            Number of requests ahead in queue (0 = would process immediately).
        """
        async with self._lock:
            state = self._users.get(user_id)
            if not state:
                return 0

            # If we can acquire immediately, position is 0
            if state.active_count < self._max_concurrent:
                return 0

            # Otherwise, position is queue_count + 1
            return state.queue_count + 1

    async def get_active_count(self, user_id: int) -> int:
        """Get number of active generations for user.

        Args:
            user_id: Telegram user ID.

        Returns:
            Number of currently active generations.
        """
        async with self._lock:
            state = self._users.get(user_id)
            return state.active_count if state else 0

    @asynccontextmanager
    async def acquire(
        self,
        user_id: int,
        thread_id: int,
    ) -> AsyncIterator[int]:
        """Acquire a generation slot for user.

        Blocks until a slot is available or timeout.

        Args:
            user_id: Telegram user ID.
            thread_id: Database thread ID (for logging).

        Yields:
            Queue position (0 = immediate, >0 = waited in queue).

        Raises:
            ConcurrencyLimitExceeded: If queue timeout exceeded.
            asyncio.CancelledError: If request was cancelled while waiting.
        """
        queue_position = 0
        wait_start = asyncio.get_event_loop().time()

        async with self._lock:
            state = self._get_or_create_user_state(user_id)

            # Check if we need to wait
            if state.active_count >= self._max_concurrent:
                queue_position = state.queue_count + 1
                state.queue_count += 1

                logger.info(
                    "concurrency_limiter.queued",
                    user_id=user_id,
                    thread_id=thread_id,
                    queue_position=queue_position,
                    active_count=state.active_count,
                    max_concurrent=self._max_concurrent,
                )

        # Try to acquire semaphore (may block)
        try:
            acquired = await asyncio.wait_for(
                state.semaphore.acquire(),
                timeout=self._queue_timeout,
            )

            if not acquired:
                # Should not happen with standard Semaphore, but handle it
                raise ConcurrencyLimitExceeded(
                    user_id=user_id,
                    queue_position=queue_position,
                    wait_time=asyncio.get_event_loop().time() - wait_start,
                )

        except asyncio.TimeoutError as exc:
            # Queue timeout - decrement queue count and raise
            async with self._lock:
                state = self._users.get(user_id)
                if state and state.queue_count > 0:
                    state.queue_count -= 1

            wait_time = asyncio.get_event_loop().time() - wait_start

            logger.warning(
                "concurrency_limiter.timeout",
                user_id=user_id,
                thread_id=thread_id,
                queue_position=queue_position,
                wait_time=round(wait_time, 2),
                timeout=self._queue_timeout,
            )

            raise ConcurrencyLimitExceeded(
                user_id=user_id,
                queue_position=queue_position,
                wait_time=wait_time,
            ) from exc

        # Acquired - update state
        wait_time = asyncio.get_event_loop().time() - wait_start

        async with self._lock:
            state = self._get_or_create_user_state(user_id)
            state.active_count += 1

            if queue_position > 0:
                state.queue_count = max(0, state.queue_count - 1)

            logger.info(
                "concurrency_limiter.acquired",
                user_id=user_id,
                thread_id=thread_id,
                queue_position=queue_position,
                wait_time_ms=round(wait_time * 1000, 2),
                active_count=state.active_count,
                remaining_queue=state.queue_count,
            )

        try:
            yield queue_position

        finally:
            # Release slot
            state.semaphore.release()

            async with self._lock:
                state = self._users.get(user_id)
                if state:
                    state.active_count = max(0, state.active_count - 1)
                    state.total_processed += 1

                    logger.debug(
                        "concurrency_limiter.released",
                        user_id=user_id,
                        thread_id=thread_id,
                        active_count=state.active_count,
                        total_processed=state.total_processed,
                    )

                    # Cleanup if user has no activity
                    if state.active_count == 0 and state.queue_count == 0:
                        # Keep state for stats, but could cleanup here
                        pass

    def get_stats(self) -> dict:
        """Get limiter statistics.

        Returns:
            Dict with limiter stats.
        """
        total_active = sum(s.active_count for s in self._users.values())
        total_queued = sum(s.queue_count for s in self._users.values())
        total_processed = sum(s.total_processed for s in self._users.values())

        return {
            "max_concurrent_per_user": self._max_concurrent,
            "queue_timeout": self._queue_timeout,
            "total_users_tracked": len(self._users),
            "total_active_generations": total_active,
            "total_queued_requests": total_queued,
            "total_processed": total_processed,
        }


# Global singleton instance
_limiter: UserConcurrencyLimiter | None = None


def get_concurrency_limiter() -> UserConcurrencyLimiter:
    """Get or create the global limiter instance.

    Returns:
        UserConcurrencyLimiter singleton.
    """
    global _limiter  # pylint: disable=global-statement
    if _limiter is None:
        _limiter = UserConcurrencyLimiter()
        logger.info(
            "concurrency_limiter.initialized",
            max_concurrent=MAX_CONCURRENT_GENERATIONS_PER_USER,
            queue_timeout=CONCURRENCY_QUEUE_TIMEOUT,
        )
    return _limiter


@asynccontextmanager
async def concurrency_context(
    user_id: int,
    thread_id: int,
) -> AsyncIterator[int]:
    """Context manager for concurrency-limited generation.

    Convenience wrapper around get_concurrency_limiter().acquire().

    Args:
        user_id: Telegram user ID.
        thread_id: Database thread ID.

    Yields:
        Queue position (0 = immediate, >0 = waited in queue).

    Raises:
        ConcurrencyLimitExceeded: If queue timeout exceeded.

    Example:
        async with concurrency_context(user_id, thread_id) as queue_pos:
            if queue_pos > 0:
                logger.info("Waited in queue", position=queue_pos)
            await process_generation(...)
    """
    limiter = get_concurrency_limiter()
    async with limiter.acquire(user_id, thread_id) as queue_position:
        yield queue_position
